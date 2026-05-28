"""Asyncio WebSocket server for Wispr Dragon speech-to-text service."""

import asyncio
import json
import logging
from typing import Optional
import websockets
from websockets.server import WebSocketServerProtocol

from wispr_dragon.config import Config
from wispr_dragon.server.audio_receiver import WebSocketAudioReceiver

logger = logging.getLogger(__name__)


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

        try:
            await websocket.send(json.dumps({"type": "ready", "server_version": "1.0.0"}))
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
        else:
            logger.warning("Unknown message type: %s", msg_type)

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
