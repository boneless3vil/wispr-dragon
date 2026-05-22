"""WebSocket client for connecting to Wispr Dragon server."""

import asyncio
import json
import logging
from typing import Optional, Callable
import websockets

logger = logging.getLogger(__name__)


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
        self._reconnect_count = 0
        self._max_reconnect_count = 10

    async def connect(self) -> bool:
        """Connect to the WebSocket server.

        Returns:
            True if connected, False otherwise
        """
        try:
            logger.info("Connecting to %s", self.server_url)
            self.websocket = await websockets.connect(
                self.server_url,
                extra_headers={"Authorization": f"Bearer {self.api_key}"},
            )
            self._reconnect_count = 0
            logger.info("Connected to server")
            if self.on_status:
                self.on_status("connected")
            return True

        except Exception as e:
            logger.error("Connection failed: %s", e)
            if self.on_error:
                self.on_error(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from server and stop the client for good.

        This is the user-initiated stop. To tear down a single connection
        while leaving the client free to reconnect, use _close_socket().
        """
        self._running = False
        await self._close_socket()
        logger.info("Disconnected")
        if self.on_status:
            self.on_status("disconnected")

    async def _close_socket(self) -> None:
        """Close the current socket without stopping the client.

        Clears self.websocket so run()'s reconnect path re-establishes it.
        """
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None

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

    async def listen(self) -> None:
        """Listen for messages from server.

        Runs indefinitely until disconnected or error.
        """
        if not self.websocket:
            return

        try:
            async for message in self.websocket:
                try:
                    if isinstance(message, str):
                        data = json.loads(message)
                        msg_type = data.get("type")

                        if msg_type == "ready":
                            logger.info("Server ready: %s", data.get("server_version"))
                        elif msg_type == "transcript":
                            text = data.get("text", "")
                            if text and self.on_transcript:
                                logger.debug("Received: %s", text)
                                self.on_transcript(text)
                        elif msg_type == "pong":
                            pass  # keepalive response
                        elif msg_type == "error":
                            code = data.get("code")
                            msg = data.get("message")
                            logger.error("Server error: %s (%s)", msg, code)
                            if self.on_error:
                                self.on_error(f"Server error: {msg}")
                        else:
                            logger.debug("Unknown message type: %s", msg_type)

                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from server: %s", message[:100])

        except websockets.exceptions.ConnectionClosed as e:
            # 4001 = server rejected our credentials. Reconnecting would just
            # storm the server with the same bad key, so stop for good.
            if getattr(e, "code", None) == 4001:
                logger.error("Server rejected credentials (unauthorized)")
                self._running = False
                if self.on_error:
                    self.on_error("Authentication failed — check the API key")
            else:
                logger.info("Connection closed by server")
        except Exception as e:
            logger.error("Error in listen: %s", e)
            if self.on_error:
                self.on_error(f"Listen error: {e}")

    async def run(self, audio_queue: asyncio.Queue) -> None:
        """Main client loop: handle connection, streaming, and reconnects.

        Args:
            audio_queue: asyncio.Queue supplying audio chunks
        """
        self._running = True

        while self._running:
            if not self.websocket:
                if not await self.connect():
                    self._reconnect_count += 1
                    if self._reconnect_count > self._max_reconnect_count:
                        logger.error(
                            "Giving up after %d failed reconnect attempts",
                            self._max_reconnect_count,
                        )
                        if self.on_status:
                            self.on_status("failed")
                        break
                    wait_time = min(2 ** self._reconnect_count, 32)
                    logger.info(
                        "Reconnecting in %d seconds (attempt %d/%d)...",
                        wait_time, self._reconnect_count, self._max_reconnect_count,
                    )
                    if self.on_status:
                        self.on_status(f"reconnecting ({self._reconnect_count})")
                    await asyncio.sleep(wait_time)
                    continue

            # Connection is up: pump audio out and transcripts in until either
            # side ends — a clean server close, a socket error, or stop().
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
                    if self.on_error:
                        self.on_error(f"Connection error: {result}")

            # Tear down this connection but keep the client running so the
            # loop's reconnect path (with backoff) re-establishes it.
            await self._close_socket()
            if not self._running:
                break
            logger.info("Connection lost — will attempt to reconnect")
            if self.on_status:
                self.on_status("disconnected")

        logger.info("Client stopped")

    async def _feed_audio(self, audio_queue: asyncio.Queue) -> None:
        """Feed audio from queue to server.

        Args:
            audio_queue: asyncio.Queue with audio chunks
        """
        while self._running and self.websocket:
            try:
                audio_bytes = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Error feeding audio: %s", e)
                break

            # A failed send means the socket is dead — end the task so run()
            # tears the connection down and reconnects.
            if audio_bytes and not await self.send_audio(audio_bytes):
                break

    def stop(self) -> None:
        """Request client to stop."""
        self._running = False
