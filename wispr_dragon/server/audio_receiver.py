"""WebSocket-based audio receiver that mirrors NetworkAudioCapture interface."""

import asyncio
import logging
import numpy as np
import queue
from typing import Optional

logger = logging.getLogger(__name__)


class WebSocketAudioReceiver:
    """Receives audio chunks from WebSocket connection and exposes queue-based interface.

    Implements the same interface as NetworkAudioCapture so it's a drop-in replacement
    in the main pipeline loop.
    """

    def __init__(self, audio_queue: asyncio.Queue, sample_rate: int = 16000, channels: int = 1):
        """Initialize receiver.

        Args:
            audio_queue: asyncio.Queue that receives binary audio frames
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels
        """
        self.audio_queue = audio_queue
        self.sample_rate = sample_rate
        self.channels = channels
        self._running = False
        self._sync_queue = queue.Queue()
        self._consumer_task = None

    @property
    def is_running(self) -> bool:
        """Check if audio receiver is active."""
        return self._running

    def start(self) -> None:
        """Start listening for audio (no-op for WebSocket mode)."""
        self._running = True
        logger.debug("WebSocket audio receiver started")

    def stop(self) -> None:
        """Stop listening for audio."""
        self._running = False
        logger.debug("WebSocket audio receiver stopped")

    def read(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """Read one audio chunk (blocking, thread-safe).

        Args:
            timeout: Timeout in seconds for reading from queue

        Returns:
            numpy array of int16 audio samples, or None if timeout
        """
        if not self._running:
            return None

        try:
            audio_bytes = self._sync_queue.get(timeout=timeout)
            if audio_bytes is None:
                return None

            audio = np.frombuffer(audio_bytes, dtype=np.int16)
            return audio.astype(np.float32) / 32768.0

        except queue.Empty:
            return None
        except Exception as e:
            logger.error("Error reading audio: %s", e)
            return None

    async def queue_audio(self, audio_bytes: bytes) -> None:
        """Queue audio bytes from WebSocket handler (async).

        Called by the WebSocket server when a binary frame arrives.

        Args:
            audio_bytes: raw binary audio data (int16 PCM)
        """
        try:
            self._sync_queue.put(audio_bytes, block=False)
        except queue.Full:
            logger.warning("Audio queue full, dropping frame")
