"""WebSocket client for connecting to Wispr Dragon server."""

import asyncio
import json
import logging
from typing import Optional, Callable
import websockets

logger = logging.getLogger(__name__)

# Close codes the server uses to refuse a connection (server/websocket_server.py).
CLOSE_ALREADY_CONNECTED = 4000  # another client holds the single connection slot
CLOSE_UNAUTHORIZED = 4001       # bad / missing API key

# Reconnect backoff: min(2 ** attempt, cap) seconds. There is deliberately no
# attempt limit — a server that is down or still loading its model is a
# transient condition, and a client that silently exits is worse than one that
# keeps (slowly) retrying.
_MAX_BACKOFF_S = 32
# After a 4000 "already connected" refusal: the server refuses cheaply, and the
# usual cause (a half-open socket from our own previous session) clears within
# ~40 s, so retry more often than for an unreachable server.
_BUSY_MAX_BACKOFF_S = 8
# How long the websockets closing handshake may take, and how long we wait for
# close() as a whole. On a dead network the library default (10 s) made Quit hang.
_CLOSE_TIMEOUT_S = 2
_CLOSE_WAIT_S = 3


class WebSocketClient:
    """Connects to server, streams audio, receives transcriptions."""

    def __init__(
        self,
        server_url: str,
        api_key: str,
        on_transcript: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        """Initialize WebSocket client.

        Args:
            server_url: WebSocket server URL (e.g., ws://192.168.1.x:8765)
            api_key: API key for authentication
            on_transcript: Callback when text is transcribed
            on_error: Callback when error occurs
            on_status: Callback when connection status changes
        """
        self.server_url = server_url
        self.api_key = api_key
        self.on_transcript = on_transcript
        self.on_error = on_error
        self.on_status = on_status
        self.websocket = None
        self._running = False
        # Consecutive attempts without a working session. Reset only when the
        # server sends `ready` — NOT when the TCP/HTTP handshake succeeds: a
        # server that accepts the handshake and then refuses us (close 4000,
        # "already connected") would otherwise reset it every time and the
        # client would reconnect in a tight loop.
        self._reconnect_count = 0
        # Set when the server rejects our credentials (close 4001). run() then
        # stops for good; reconnecting with the same key would only storm the
        # server. The app decides what to do next (wait for new settings).
        self.auth_failed = False
        # Wakes a backoff sleep early (stop() / reconnect_now()). Created in
        # run() so it binds to the loop that actually runs the client.
        self._wake: Optional[asyncio.Event] = None
        self._in_backoff = False
        self._skip_backoff = False
        # The last session ended in a 4000 refusal (shorter backoff cap).
        self._refused_busy = False
        # In-flight connect() task, so a settings change can abandon it; and a
        # counter bumped on each settings change, so a connect that completes
        # with the *old* settings is recognised and redone.
        self._connect_task: Optional[asyncio.Task] = None
        self._connect_abandon: Optional[asyncio.Future] = None
        self._settings_epoch = 0
        # Capabilities advertised by the server in its `ready` payload. Empty
        # until we connect (and for old servers that never send it), which is
        # what the client uses to decide whether utterance framing is available.
        self.server_features: list = []

    def supports(self, feature: str) -> bool:
        """True if the connected server advertised ``feature``."""
        return feature in self.server_features

    @property
    def is_connected(self) -> bool:
        """True while a socket is up (audio may be queued for sending)."""
        ws = self.websocket
        return ws is not None and bool(getattr(ws, "open", False))

    def _emit(self, callback: Optional[Callable[[str], None]], arg: str) -> None:
        """Invoke an app callback without letting its exceptions escape.

        A raising on_transcript (e.g. an injection error) used to propagate out
        of listen() and drop the connection.
        """
        if callback is None:
            return
        try:
            callback(arg)
        except Exception:
            logger.exception("Client callback %s raised", getattr(callback, "__name__", callback))

    async def connect(self) -> bool:
        """Connect to the WebSocket server.

        Returns:
            True if connected, False otherwise
        """
        ws = await self._open_socket()
        if ws is None:
            return False
        self._adopt(ws)
        return True

    async def _open_socket(self):
        """Open a connection with the current settings; None on failure."""
        try:
            logger.info("Connecting to %s", self.server_url)
            return await websockets.connect(
                self.server_url,
                extra_headers={"Authorization": f"Bearer {self.api_key}"},
                close_timeout=_CLOSE_TIMEOUT_S,
            )
        except Exception as e:
            # Logged once here (WARNING: it repeats on every retry while the
            # server is down); the app's on_error doesn't log it again.
            logger.warning("Connection to %s failed: %s", self.server_url, e)
            self._emit(self.on_error, f"Connection failed: {e}")
            self._emit(self.on_status, "connect_failed")
            return None

    def _adopt(self, ws) -> None:
        """Make ``ws`` the live connection."""
        self.websocket = ws
        # Note: _reconnect_count is reset on `ready`, not here (see __init__).
        logger.info("Connected to server")
        self._emit(self.on_status, "connected")

    async def disconnect(self) -> None:
        """Disconnect from server and stop the client for good.

        This is the user-initiated stop. To tear down a single connection
        while leaving the client free to reconnect, use _close_socket().
        """
        self.stop()
        await self._close_socket()
        logger.info("Disconnected")
        self._emit(self.on_status, "disconnected")

    async def _close_socket(self) -> None:
        """Close the current socket without stopping the client.

        Clears self.websocket so run()'s reconnect path re-establishes it.
        Bounded: a dead network can't stall the caller (e.g. Quit).
        """
        ws = self.websocket
        if ws:
            self.websocket = None
            try:
                await asyncio.wait_for(ws.close(), timeout=_CLOSE_WAIT_S)
            except Exception:
                pass

    def reconnect_now(self) -> None:
        """Settings changed: reconnect promptly with the new URL / key.

        Resets the backoff and makes the next attempt immediate: a pending
        backoff wait ends, an in-flight connect (using the old settings) is
        abandoned, and otherwise the wait after the coming disconnect is
        skipped. The caller still closes a live socket (``_close_socket``).
        """
        self._reconnect_count = 0
        self._settings_epoch += 1
        if self._abandon_connect():
            self._skip_backoff = False
        elif self._in_backoff and self._wake is not None:
            self._wake.set()  # end the current wait
            self._skip_backoff = False
        else:
            self._skip_backoff = True  # don't wait after the coming disconnect

    def retry_now(self) -> None:
        """Cut a pending backoff wait short (e.g. the user started dictating).

        Unlike reconnect_now(), settings are unchanged: an in-flight connect is
        left alone and nothing is skipped later.
        """
        self._reconnect_count = 0
        if self._in_backoff and self._wake is not None:
            self._wake.set()

    async def send_audio(self, audio_bytes: bytes) -> bool:
        """Send audio chunk to server.

        Args:
            audio_bytes: raw int16 PCM audio bytes

        Returns:
            True if sent, False if error
        """
        if not self.websocket:
            return False

        try:
            await self.websocket.send(audio_bytes)
            return True
        except Exception as e:
            logger.error("Error sending audio: %s", e)
            return False

    async def send_json(self, message: dict) -> bool:
        """Send a JSON control message to the server (e.g. learn_correction).

        Returns True if sent, False if there's no live socket or it failed.
        """
        if not self.websocket:
            return False
        try:
            await self.websocket.send(json.dumps(message))
            return True
        except Exception as e:
            logger.error("Error sending control message: %s", e)
            return False

    async def listen(self) -> None:
        """Listen for messages from server.

        Runs indefinitely until disconnected or error. Close codes are handled
        by run() once the session ends (see _handle_close_code).
        """
        ws = self.websocket
        if not ws:
            return

        try:
            async for message in ws:
                try:
                    if isinstance(message, str):
                        data = json.loads(message)
                        msg_type = data.get("type")

                        if msg_type == "ready":
                            self.server_features = list(data.get("features") or [])
                            # The server has accepted us: this is a working
                            # session, so the backoff starts over next time.
                            self._reconnect_count = 0
                            logger.info(
                                "Server ready: %s (features=%s)",
                                data.get("server_version"),
                                self.server_features or "none",
                            )
                            self._emit(self.on_status, "ready")
                        elif msg_type == "utterance_ack":
                            logger.debug("Utterance acked: %s", data.get("id"))
                        elif msg_type == "transcript":
                            text = data.get("text", "")
                            if text and self.on_transcript:
                                # Dictated text is private — DEBUG only.
                                logger.debug("Received: %s", text)
                                self._emit(self.on_transcript, text)
                        elif msg_type == "pong":
                            pass  # keepalive response
                        elif msg_type == "error":
                            code = data.get("code")
                            msg = data.get("message")
                            logger.error("Server error: %s (%s)", msg, code)
                            self._emit(self.on_error, f"Server error: {msg}")
                        else:
                            logger.debug("Unknown message type: %s", msg_type)

                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from server: %s", message[:100])

        except websockets.exceptions.ConnectionClosed as e:
            logger.debug("Connection closed (code=%s)", _close_code(e))
        except Exception as e:
            logger.error("Error in listen: %s", e)
            self._emit(self.on_error, f"Listen error: {e}")

    def _handle_close_code(self, code: Optional[int]) -> None:
        """React to how the server ended the session."""
        self._refused_busy = code == CLOSE_ALREADY_CONNECTED
        if code == CLOSE_UNAUTHORIZED:
            # Reconnecting would just storm the server with the same bad key,
            # so stop for good and let the app ask the user for a new one.
            logger.error("Server rejected credentials (unauthorized) - check the API key")
            self.auth_failed = True
            self._running = False
            self._emit(self.on_error, "Authentication failed — check the API key")
            self._emit(self.on_status, "unauthorized")
        elif code == CLOSE_ALREADY_CONNECTED:
            logger.warning(
                "Server busy (another client is connected) - retrying with backoff"
            )
            self._emit(self.on_status, "busy")
        elif code is not None:
            logger.info("Connection closed (code=%s)", code)

    async def _backoff(self) -> None:
        """Wait before the next connection attempt (capped exponential).

        Every lost or failed connection goes through here, so no server
        behaviour — refusing, crashing, closing right after the handshake —
        can drive the client into a tight reconnect loop.
        """
        if not self._running:
            return
        if self._skip_backoff:
            self._skip_backoff = False
            return
        self._reconnect_count += 1
        cap = _BUSY_MAX_BACKOFF_S if self._refused_busy else _MAX_BACKOFF_S
        wait_time = min(2 ** min(self._reconnect_count, 6), cap)
        logger.info(
            "Reconnecting in %d seconds (attempt %d)...", wait_time, self._reconnect_count
        )
        self._emit(self.on_status, f"reconnecting ({self._reconnect_count})")
        if self._wake is None:
            await asyncio.sleep(wait_time)
            return
        self._wake.clear()
        self._in_backoff = True
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=wait_time)
        except asyncio.TimeoutError:
            pass
        finally:
            self._in_backoff = False

    async def _connect_abandonable(self) -> Optional[bool]:
        """connect(), or None if reconnect_now() / stop() abandoned it.

        Abandoning doesn't wait for the attempt to unwind: cancelling a
        handshake in progress makes websockets wait up to ``close_timeout``
        for the peer to drop the TCP connection. The attempt is cancelled and
        left to finish in the background; a socket it still manages to open
        is closed, never adopted (it would carry the old settings).
        """
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._open_socket())
        abandon = loop.create_future()
        self._connect_task, self._connect_abandon = task, abandon
        try:
            await asyncio.wait({task, abandon}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            task.cancel()  # run() itself is being cancelled
            raise
        finally:
            self._connect_task = self._connect_abandon = None
        if task.done() and not task.cancelled():
            ws = task.result()
            if ws is None:
                return False
            self._adopt(ws)
            return True
        logger.info("Connection attempt abandoned (settings changed or stopping)")
        task.cancel()
        task.add_done_callback(_close_abandoned)
        return None

    @staticmethod
    def _drain(queue: asyncio.Queue) -> int:
        """Discard everything queued before this connection existed."""
        dropped = 0
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            dropped += 1
        if dropped:
            logger.info("Discarded %d stale queued frame(s) from before the connection", dropped)
        return dropped

    async def run(self, audio_queue: asyncio.Queue) -> None:
        """Main client loop: handle connection, streaming, and reconnects.

        Retries forever with capped backoff; ends only on stop() or when the
        server rejects our credentials (``auth_failed``).

        Args:
            audio_queue: asyncio.Queue supplying audio chunks
        """
        self._running = True
        self.auth_failed = False
        self._wake = asyncio.Event()

        while self._running:
            if not self.websocket:
                epoch = self._settings_epoch
                connected = await self._connect_abandonable()
                if epoch != self._settings_epoch:
                    # Settings changed while connecting: this attempt used the
                    # old URL / key. Drop any socket it opened and go again.
                    if connected:
                        await self._close_socket()
                    connected = None
                if connected is None:
                    continue  # abandoned for new settings: retry immediately
                if not connected:
                    self._refused_busy = False
                    await self._backoff()
                    continue
                # A fresh connection: any skip requested for an earlier
                # disconnect is stale now.
                self._skip_backoff = False
                # Anything queued while we were offline is stale: speech from
                # seconds or minutes ago must not be transcribed and typed now.
                self._drain(audio_queue)

            # Connection is up: pump audio out and transcripts in until either
            # side ends — a clean server close, a socket error, or stop().
            ws = self.websocket
            listen_task = asyncio.create_task(self.listen())
            audio_task = asyncio.create_task(self._feed_audio(audio_queue))
            try:
                done, pending = await asyncio.wait(
                    [listen_task, audio_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                for task in (listen_task, audio_task):
                    task.cancel()
                await asyncio.gather(listen_task, audio_task, return_exceptions=True)
                break

            for task in pending:
                task.cancel()
            results = await asyncio.gather(
                listen_task, audio_task, return_exceptions=True
            )
            for result in results:
                if isinstance(result, Exception) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    logger.error("Error in run loop: %s", result)
                    self._emit(self.on_error, f"Connection error: {result}")

            # Checked here rather than in listen(): if the feeder notices the
            # dead socket first, listen() is cancelled before it sees the close.
            self._handle_close_code(getattr(ws, "close_code", None))

            # Tear down this connection but keep the client running so the
            # loop's reconnect path (with backoff) re-establishes it.
            await self._close_socket()
            if not self._running:
                break
            logger.info("Connection lost - will attempt to reconnect")
            self._emit(self.on_status, "disconnected")
            await self._backoff()

        logger.info("Client stopped")

    async def _feed_audio(self, audio_queue: asyncio.Queue) -> None:
        """Feed queued items to the server, preserving their order.

        The queue carries two kinds of item:
        * ``bytes`` — an audio frame, sent as a binary message.
        * ``dict``  — a control frame (e.g. ``utterance_end``), sent as JSON.

        Control frames MUST travel through this same queue rather than being
        sent directly: otherwise an ``utterance_end`` would overtake audio still
        waiting here and the server would finalize a truncated utterance.

        Args:
            audio_queue: asyncio.Queue of audio frames and control messages
        """
        while self._running and self.websocket:
            try:
                item = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Error feeding audio: %s", e)
                break

            # A failed send means the socket is dead — end the task so run()
            # tears the connection down and reconnects.
            if isinstance(item, dict):
                if not await self.send_json(item):
                    break
            elif item and not await self.send_audio(item):
                break

    def stop(self) -> None:
        """Request client to stop (also cuts a pending backoff wait or an
        in-flight connection attempt short)."""
        self._running = False
        if self._wake is not None:
            self._wake.set()
        self._abandon_connect()

    def _abandon_connect(self) -> bool:
        """Abandon an in-flight connection attempt; True if there was one."""
        abandon = self._connect_abandon
        if abandon is None or abandon.done():
            return False
        abandon.set_result(None)
        return True


def _close_abandoned(task: asyncio.Task) -> None:
    """Done-callback for an abandoned connect: close a socket it still opened."""
    if task.cancelled():
        return
    ws = task.result()  # _open_socket() returns None instead of raising
    if ws is not None:
        try:
            asyncio.get_running_loop().create_task(ws.close())
        except RuntimeError:  # loop already gone
            pass


def _close_code(exc: Exception) -> Optional[int]:
    """Close code carried by a websockets ConnectionClosed, if any."""
    rcvd = getattr(exc, "rcvd", None)
    if rcvd is not None:
        return getattr(rcvd, "code", None)
    return getattr(exc, "code", None)
