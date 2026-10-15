"""Asyncio WebSocket server for Wispr Dragon speech-to-text service."""

import asyncio
import functools
import hmac
import json
import logging
import ssl
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Optional

import numpy as np
import websockets
from websockets.server import WebSocketServerProtocol

from wispr_dragon import __version__
from wispr_dragon.config import Config

if TYPE_CHECKING:
    from wispr_dragon.server.pipeline_runner import PipelineRunner

logger = logging.getLogger(__name__)

# Advertised in the `ready` payload so a client can tell whether this server
# understands utterance framing, and fall back to the silence-flush hack if not.
SERVER_FEATURES = ["utterance"]

# Incoming message limits. Clients stream 30 ms int16 frames (960 bytes); the
# caps leave generous headroom while keeping one connection from ballooning
# server memory with oversized frames or an unread backlog.
MAX_MESSAGE_BYTES = 256 * 1024
MAX_QUEUED_FRAMES = 2000  # audio frames awaiting the engine: ~60 s at 30 ms
MAX_CORRECTION_CHARS = 200


class WebSocketServer:
    """Manages WebSocket connections and coordinates audio/transcription.

    Everything a connection sends — audio frames and the ``utterance_start`` /
    ``utterance_end`` markers — goes through ONE ordered queue consumed by
    :meth:`_process_events`, so markers take effect exactly where they sat on
    the wire. (Applying markers on arrival while audio waited in a separate
    queue let a quick re-press merge or drop the previous utterance.)
    Engine work runs on a single worker thread, which serializes transcription
    and dictionary updates across connections.
    """

    def __init__(self, config: Config, pipeline_runner: "PipelineRunner"):
        """Initialize WebSocket server.

        Args:
            config: Config object with server settings
            pipeline_runner: PipelineRunner instance to process audio
        """
        self.config = config
        self.pipeline_runner = pipeline_runner
        self.host = config.server.host
        self.port = config.server.port
        self.sample_rate = config.audio.sample_rate
        self.active_connection: Optional[WebSocketServerProtocol] = None
        self.process_task: Optional[asyncio.Task] = None
        self._events: Optional[asyncio.Queue] = None
        self._queued_audio = 0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wispr-engine")
        self._paused = False

        # --- utterance mode (connection-scoped) ---
        # A connection stays in legacy VAD-segmentation mode until the client
        # sends its first `utterance_start`; then it latches into utterance mode
        # for the rest of its life. That keeps older clients working untouched.
        self._utterance_mode = False
        self._utterance_buf: list = []
        self._utterance_samples = 0
        self._utterance_id: Optional[str] = None
        self._max_utterance_samples = int(
            self.sample_rate * config.audio.max_utterance_seconds
        )

    async def _run_engine(self, fn, *args, **kwargs):
        """Run blocking pipeline work on the single engine thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, functools.partial(fn, *args, **kwargs))

    def _authorized(self, websocket: WebSocketServerProtocol) -> bool:
        api_key = self.config.server.api_key
        if not api_key:
            return True
        provided = websocket.request_headers.get("Authorization", "")
        # websockets decodes headers as ASCII + surrogateescape; round-trip the
        # same way so a junk header is a plain mismatch, not an exception.
        return hmac.compare_digest(
            provided.encode("utf-8", "surrogateescape"),
            f"Bearer {api_key}".encode("utf-8", "surrogateescape"),
        )

    async def handler(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            path: Connection path (unused)
        """
        logger.info("New connection from %s", websocket.remote_address)

        # Authenticate: if an API key is configured, require a matching bearer token.
        if not self._authorized(websocket):
            logger.warning(
                "Rejecting connection from %s: unauthorized", websocket.remote_address
            )
            await websocket.close(code=4001, reason="unauthorized")
            return

        if self.active_connection is not None and self.active_connection != websocket:
            logger.warning("Rejecting connection: max_connections=1 already active")
            await websocket.close(code=4000, reason="already_connected")
            return

        self.active_connection = websocket
        # Unbounded so a control marker never blocks the handler; audio is
        # capped separately by _queued_audio.
        self._events = asyncio.Queue()
        self._queued_audio = 0
        self._paused = False
        self._reset_utterance()
        self._utterance_mode = False

        try:
            await websocket.send(json.dumps({
                "type": "ready",
                "server_version": __version__,
                "features": SERVER_FEATURES,
            }))
            logger.info("Sent ready signal to client")

            self.process_task = asyncio.create_task(self._process_events(websocket))

            async for message in websocket:
                if isinstance(message, bytes):
                    self._queue_audio(message)
                    continue
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from client: %s", message[:100])
                    continue
                if not isinstance(data, dict):
                    logger.warning("Ignoring non-object control message")
                    continue
                await self._handle_control_message(data, websocket)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed by client")
        except Exception:
            logger.exception("Error in connection handler")
            try:
                await websocket.close(code=1011, reason="internal_error")
            except Exception:
                pass
        finally:
            if self.process_task:
                self.process_task.cancel()
                try:
                    await self.process_task
                except asyncio.CancelledError:
                    pass
            # A partial utterance has nowhere to be delivered — drop it rather
            # than transcribing into a closed socket.
            if self._utterance_buf:
                logger.info("Discarding partial utterance on disconnect")
            self._reset_utterance()
            # Legacy VAD-segmentation state must not leak into the next session.
            vad = getattr(self.pipeline_runner, "vad", None)
            if vad is not None:
                self._executor.submit(vad.reset)
            self.active_connection = None
            self._events = None
            self.process_task = None
            logger.info("Connection closed")

    def _queue_audio(self, frame: bytes) -> None:
        """Decode one int16 PCM frame and queue it behind earlier events."""
        if len(frame) % 2 or len(frame) > MAX_MESSAGE_BYTES:
            logger.warning("Dropping malformed audio frame (%d bytes)", len(frame))
            return
        if self._queued_audio >= MAX_QUEUED_FRAMES:
            logger.warning("Audio queue full, dropping frame")
            return
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        self._queued_audio += 1
        self._events.put_nowait(("audio", audio))

    async def _handle_control_message(self, data: dict, websocket: WebSocketServerProtocol) -> None:
        """Handle control messages from client.

        Args:
            data: Parsed JSON message
            websocket: WebSocket connection
        """
        msg_type = data.get("type")

        if msg_type in ("pause", "resume"):
            # In wire order, like the utterance markers: frames sent before a
            # pause are still transcribed.
            self._events.put_nowait((msg_type, None))
            logger.debug("Client %sd recording", msg_type)
        elif msg_type == "ping":
            ts = data.get("ts", 0)
            await websocket.send(json.dumps({"type": "pong", "ts": ts}))
        elif msg_type == "learn_correction":
            await self._handle_learn_correction(data, websocket)
        elif msg_type == "utterance_start":
            utterance_id = data.get("id")
            # Markers wait behind any audio already queued (never dropped).
            self._events.put_nowait(("start", utterance_id))
            try:
                await websocket.send(json.dumps({"type": "utterance_ack", "id": utterance_id}))
            except Exception:
                pass
        elif msg_type == "utterance_end":
            self._events.put_nowait(("end", data.get("id")))
            logger.debug("Utterance end requested: %s", data.get("id"))
        else:
            logger.warning("Unknown message type: %s", msg_type)

    def _begin_utterance(self, utterance_id: Optional[str]) -> None:
        """Start buffering a hotkey-delimited utterance.

        The first such marker latches this connection into utterance mode. A
        fresh start while a buffer is in flight (rapid re-press / barge-in)
        discards the old audio rather than emitting a stale transcript.
        """
        if not self._utterance_mode:
            logger.info("Client uses utterance framing — VAD will trim, not split")
            self._utterance_mode = True
        if self._utterance_buf:
            logger.debug("Discarding in-flight utterance buffer on new start")
        self._reset_utterance()
        self._utterance_id = utterance_id

    def _reset_utterance(self) -> None:
        """Drop any buffered utterance audio (also used on disconnect)."""
        self._utterance_buf = []
        self._utterance_samples = 0
        self._utterance_id = None

    async def _handle_learn_correction(self, data: dict, websocket: WebSocketServerProtocol) -> None:
        """Persist a learned correction so it auto-applies to future transcripts.

        "always" records it at the auto-apply threshold so the fix applies
        without confirmation next time; otherwise it is one observation.
        """
        wrong, correct = data.get("wrong"), data.get("correct")
        if not isinstance(wrong, str) or not isinstance(correct, str):
            logger.warning("learn_correction ignored: fields must be strings")
            return
        wrong, correct = wrong.strip(), correct.strip()
        if not wrong or not correct:
            return
        if len(wrong) > MAX_CORRECTION_CHARS or len(correct) > MAX_CORRECTION_CHARS:
            logger.warning("learn_correction ignored: longer than %d chars", MAX_CORRECTION_CHARS)
            return
        dictionary = getattr(self.pipeline_runner, "dictionary", None)
        if dictionary is None:
            logger.warning("learn_correction received but no dictionary loaded")
            return
        always = bool(data.get("always"))
        count = max(self.config.correction.auto_apply_threshold, 1) if always else 1
        # On the engine thread, so it never mutates the dictionary mid-transcript.
        await self._run_engine(dictionary.add_correction, wrong, correct, count=count)
        logger.info("Learned correction: '%s' -> '%s' (always=%s)", wrong, correct, always)
        try:
            await websocket.send(json.dumps({
                "type": "correction_learned", "wrong": wrong, "correct": correct,
            }))
        except Exception:
            pass

    async def _finalize_utterance(self, websocket: WebSocketServerProtocol,
                                  continued: bool = False) -> None:
        """Transcribe the buffered utterance in one pass and send the result.

        ``continued=True`` means the max-length valve fired mid-utterance rather
        than the user releasing the hotkey; the id is kept so the client can tell
        the pieces belong together, and buffering resumes for the remainder.
        """
        if not self._utterance_buf:
            self._utterance_samples = 0
            return

        audio = np.concatenate(self._utterance_buf)
        utterance_id = self._utterance_id
        self._utterance_buf = []
        self._utterance_samples = 0
        if not continued:
            self._utterance_id = None

        result = await self._run_engine(self.pipeline_runner.process_utterance, audio)
        if not result:
            return
        try:
            await websocket.send(json.dumps({
                "type": "transcript",
                "text": result,
                "final": True,
                "language": self.config.engine.language,
                "duration": audio.shape[0] / self.sample_rate,
                "id": utterance_id,
                "utterance": True,
                "continued": continued,
            }))
            logger.debug("Sent utterance transcript: %s", result)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed while sending utterance transcript")

    async def _process_events(self, websocket: WebSocketServerProtocol) -> None:
        """Consume this connection's events in wire order.

        Runs in background as a task for each connection.
        """
        events = self._events
        try:
            while True:
                kind, payload = await events.get()

                if kind == "audio":
                    self._queued_audio -= 1
                if kind == "start":
                    self._begin_utterance(payload)
                elif kind == "end":
                    await self._finalize_utterance(websocket)
                elif kind in ("pause", "resume"):
                    self._paused = kind == "pause"
                elif self._paused:
                    continue  # audio while paused is consumed, not transcribed
                elif self._utterance_mode:
                    # Accumulate; the hotkey (not the VAD) delimits the utterance.
                    self._utterance_buf.append(payload)
                    self._utterance_samples += payload.shape[0]
                    if self._utterance_samples >= self._max_utterance_samples:
                        logger.info("Utterance hit max length — force-finalizing")
                        await self._finalize_utterance(websocket, continued=True)
                else:
                    await self._process_legacy_frame(websocket, payload)

        except asyncio.CancelledError:
            raise
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed while sending transcript")
        except Exception as e:
            # Don't leave the client streaming into a queue nobody reads: report
            # and close, so it reconnects to a fresh session.
            logger.exception("Error in audio processing loop")
            try:
                await websocket.send(json.dumps({
                    "type": "error", "code": "pipeline_error", "message": str(e),
                }))
                await websocket.close(code=1011, reason="pipeline_error")
            except Exception:
                pass

    async def _process_legacy_frame(self, websocket: WebSocketServerProtocol,
                                    audio: np.ndarray) -> None:
        """Legacy clients: VAD splits the continuous stream into segments."""
        result = await self._run_engine(self.pipeline_runner.process, audio)
        if result:
            await websocket.send(json.dumps({
                "type": "transcript",
                "text": result,
                "final": True,
                "language": self.config.engine.language,
                "duration": audio.shape[0] / self.sample_rate,
            }))
            logger.debug("Sent transcript: %s", result)

    def _ssl_context(self) -> Optional[ssl.SSLContext]:
        """TLS context from server.tls_cert/tls_key, or None for plain ws://."""
        cert, key = self.config.server.tls_cert, self.config.server.tls_key
        if not cert and not key:
            return None
        if not (cert and key):
            raise ValueError("server.tls_cert and server.tls_key must be set together")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        return context

    async def start(self) -> None:
        """Start the WebSocket server (blocks until stopped)."""
        ssl_context = self._ssl_context()
        scheme = "wss" if ssl_context else "ws"
        logger.info("Starting WebSocket server on %s://%s:%d", scheme, self.host, self.port)
        if not self.config.server.api_key:
            logger.warning(
                "No api_key configured — server accepts unauthenticated connections. "
                "Run with --print-key to generate one."
            )

        async with websockets.serve(
            self.handler, self.host, self.port,
            ssl=ssl_context, max_size=MAX_MESSAGE_BYTES,
        ):
            logger.info("WebSocket server listening")
            # KeyboardInterrupt surfaces at the asyncio.run() boundary in
            # _handle_server_mode, not here — just wait forever.
            await asyncio.Future()
