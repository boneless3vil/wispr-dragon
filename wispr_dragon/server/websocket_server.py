"""Asyncio WebSocket server for Wispr Dragon speech-to-text service."""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Optional

import numpy as np
import websockets
from websockets.server import WebSocketServerProtocol

from wispr_dragon.config import Config
from wispr_dragon.server.audio_receiver import WebSocketAudioReceiver

if TYPE_CHECKING:
    from wispr_dragon.server.pipeline_runner import PipelineRunner

logger = logging.getLogger(__name__)

# Advertised in the `ready` payload so a client can tell whether this server
# understands utterance framing, and fall back to the silence-flush hack if not.
SERVER_FEATURES = ["utterance"]


class WebSocketServer:
    """Manages WebSocket connections and coordinates audio/transcription."""

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
        self.active_connection: Optional[WebSocketServerProtocol] = None
        self.audio_receiver: Optional[WebSocketAudioReceiver] = None
        self.process_task: Optional[asyncio.Task] = None
        self._paused = False

        # --- utterance mode (connection-scoped) ---
        # A connection stays in legacy VAD-segmentation mode until the client
        # sends its first `utterance_start`; then it latches into utterance mode
        # for the rest of its life. That keeps older clients working untouched.
        self._utterance_mode = False
        self._utterance_buf: list = []
        self._utterance_samples = 0
        self._utterance_id: Optional[str] = None
        # Set by the handler coroutine on `utterance_end`; consumed by the audio
        # loop once it has drained the last queued frames.
        self._utterance_end_pending = False
        self._max_utterance_samples = int(
            config.audio.sample_rate * config.audio.max_utterance_seconds
        )

    async def handler(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            path: Connection path (unused)
        """
        logger.info("New connection from %s", websocket.remote_address)

        # Authenticate: if an API key is configured, require a matching bearer token.
        api_key = self.config.server.api_key
        if api_key:
            provided = websocket.request_headers.get("Authorization", "")
            if provided != f"Bearer {api_key}":
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
        self.audio_receiver = WebSocketAudioReceiver(sample_rate=16000, channels=1)
        self._paused = False
        self._reset_utterance()
        self._utterance_mode = False

        try:
            await websocket.send(json.dumps({
                "type": "ready",
                "server_version": "1.0.0",
                "features": SERVER_FEATURES,
            }))
            logger.info("Sent ready signal to client")

            self.audio_receiver.start()
            self.process_task = asyncio.create_task(self._process_audio_loop())

            async for message in websocket:
                if isinstance(message, bytes):
                    await self.audio_receiver.queue_audio(message)
                else:
                    try:
                        data = json.loads(message)
                        await self._handle_control_message(data, websocket)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from client: %s", message[:100])

        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed by client")
        except Exception as e:
            logger.error("Error in connection handler: %s", e)
            try:
                await websocket.close(code=4011, reason="internal_error")
            except Exception:
                pass
        finally:
            self.audio_receiver.stop()
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
            self.active_connection = None
            self.audio_receiver = None
            self.process_task = None
            logger.info("Connection closed")

    async def _handle_control_message(self, data: dict, websocket: WebSocketServerProtocol) -> None:
        """Handle control messages from client.

        Args:
            data: Parsed JSON message
            websocket: WebSocket connection
        """
        msg_type = data.get("type")

        if msg_type == "pause":
            self._paused = True
            logger.debug("Client paused recording")
        elif msg_type == "resume":
            self._paused = False
            logger.debug("Client resumed recording")
        elif msg_type == "ping":
            ts = data.get("ts", 0)
            await websocket.send(json.dumps({"type": "pong", "ts": ts}))
        elif msg_type == "learn_correction":
            await self._handle_learn_correction(data, websocket)
        elif msg_type == "utterance_start":
            await self._handle_utterance_start(data, websocket)
        elif msg_type == "utterance_end":
            # The audio loop finalizes once it has drained the frames that
            # preceded this frame on the wire (WebSocket preserves order).
            self._utterance_end_pending = True
            logger.debug("Utterance end requested: %s", data.get("id"))
        else:
            logger.warning("Unknown message type: %s", msg_type)

    async def _handle_utterance_start(self, data: dict, websocket: WebSocketServerProtocol) -> None:
        """Begin buffering a hotkey-delimited utterance.

        The first such message latches this connection into utterance mode. A
        fresh start while a buffer is in flight (rapid re-press / barge-in)
        discards the old audio rather than emitting a stale transcript.
        """
        if not self._utterance_mode:
            logger.info("Client uses utterance framing — VAD will trim, not split")
            self._utterance_mode = True
        if self._utterance_buf:
            logger.debug("Discarding in-flight utterance buffer on new start")
        self._reset_utterance()
        self._utterance_id = data.get("id")
        try:
            await websocket.send(
                json.dumps({"type": "utterance_ack", "id": self._utterance_id})
            )
        except Exception:
            pass

    def _reset_utterance(self) -> None:
        """Drop any buffered utterance audio (also used on disconnect)."""
        self._utterance_buf = []
        self._utterance_samples = 0
        self._utterance_id = None
        self._utterance_end_pending = False

    async def _handle_learn_correction(self, data: dict, websocket: WebSocketServerProtocol) -> None:
        """Persist a learned correction so it auto-applies to future transcripts.

        "always" bumps the frequency past auto_apply_threshold (repeat ×3, the
        same trick the correction window uses) so the fix applies without
        confirmation next time.
        """
        wrong = (data.get("wrong") or "").strip()
        correct = (data.get("correct") or "").strip()
        if not wrong or not correct:
            return
        dictionary = getattr(self.pipeline_runner, "dictionary", None)
        if dictionary is None:
            logger.warning("learn_correction received but no dictionary loaded")
            return
        repeats = 3 if data.get("always") else 1
        for _ in range(repeats):
            dictionary.add_correction(wrong, correct)
        logger.info("Learned correction: '%s' -> '%s' (always=%s)", wrong, correct, bool(data.get("always")))
        try:
            await websocket.send(json.dumps({
                "type": "correction_learned", "wrong": wrong, "correct": correct,
            }))
        except Exception:
            pass

    async def _finalize_utterance(self, continued: bool = False) -> None:
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

        result = await asyncio.to_thread(self.pipeline_runner.process_utterance, audio)
        if not result or not self.active_connection:
            return
        try:
            await self.active_connection.send(json.dumps({
                "type": "transcript",
                "text": result,
                "final": True,
                "language": "en",
                "duration": audio.shape[0] / self.config.audio.sample_rate,
                "id": utterance_id,
                "utterance": True,
                "continued": continued,
            }))
            logger.debug("Sent utterance transcript: %s", result)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed while sending utterance transcript")

    async def _process_audio_loop(self) -> None:
        """Process audio chunks and send transcriptions back.

        Runs in background as a task for each connection.
        """
        if not self.audio_receiver or not self.active_connection:
            return

        while self.active_connection:
            try:
                # read() blocks up to `timeout` when the queue is empty, so this
                # loop idles without spinning. No extra sleep — an artificial
                # delay here makes the consumer slower than real-time audio and
                # the bounded queue then drops frames during sustained speech.
                audio_chunk = await asyncio.to_thread(self.audio_receiver.read, timeout=0.1)

                if self._utterance_mode:
                    # Accumulate; the hotkey (not the VAD) delimits the utterance.
                    if audio_chunk is not None:
                        if not self._paused:
                            self._utterance_buf.append(audio_chunk)
                            self._utterance_samples += audio_chunk.shape[0]
                            if self._utterance_samples >= self._max_utterance_samples:
                                logger.info("Utterance hit max length — force-finalizing")
                                await self._finalize_utterance(continued=True)
                        continue
                    # read() returned None => the queue is drained, so every
                    # frame that preceded `utterance_end` on the wire is buffered.
                    if self._utterance_end_pending:
                        self._utterance_end_pending = False
                        await self._finalize_utterance()
                    continue

                if audio_chunk is None:
                    continue

                # While paused, keep draining the queue (read() above consumed
                # the frame) but skip transcription.
                if self._paused:
                    continue

                result = await asyncio.to_thread(
                    self.pipeline_runner.process,
                    audio_chunk,
                )

                if result:
                    try:
                        await self.active_connection.send(
                            json.dumps({
                                "type": "transcript",
                                "text": result,
                                "final": True,
                                "language": "en",
                                "duration": audio_chunk.shape[0] / 16000,
                            })
                        )
                        logger.debug("Sent transcript: %s", result)
                    except websockets.exceptions.ConnectionClosed:
                        logger.info("Connection closed while sending transcript")
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in audio processing loop: %s", e)
                if self.active_connection:
                    try:
                        await self.active_connection.send(
                            json.dumps({
                                "type": "error",
                                "code": "pipeline_error",
                                "message": str(e),
                            })
                        )
                    except Exception:
                        pass
                break

    async def start(self) -> None:
        """Start the WebSocket server (blocks until stopped)."""
        logger.info("Starting WebSocket server on ws://%s:%d", self.host, self.port)
        if not self.config.server.api_key:
            logger.warning(
                "No api_key configured — server accepts unauthenticated connections. "
                "Run with --print-key to generate one."
            )

        async with websockets.serve(self.handler, self.host, self.port):
            logger.info("WebSocket server listening")
            # KeyboardInterrupt surfaces at the asyncio.run() boundary in
            # _handle_server_mode, not here — just wait forever.
            await asyncio.Future()
