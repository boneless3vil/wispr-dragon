"""Windows audio capture using sounddevice."""

import asyncio
import logging
import numpy as np
import sounddevice as sd
from typing import Optional

logger = logging.getLogger(__name__)


class WindowsAudioCapture:
    """Captures audio from Windows microphone and feeds to asyncio queue."""

    def __init__(self, sample_rate: int = 16000, device: Optional[int] = None):
        """Initialize audio capture.

        Args:
            sample_rate: Sample rate in Hz (default 16000 for Whisper)
            device: Device index, or None for default
        """
        self.sample_rate = sample_rate
        self.device = device
        self.channels = 1
        self.blocksize = 480  # 30ms at 16kHz
        self._stream = None
        self._running = False
        self._paused = False
        self._queue = None

    async def start(self, queue: asyncio.Queue) -> None:
        """Start capturing audio and queueing to the provided asyncio queue.

        Args:
            queue: asyncio.Queue to put audio chunks into
        """
        self._queue = queue
        self._running = True

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                device=self.device,
                blocksize=self.blocksize,
                dtype=np.int16,
                latency="low",
            )
            self._stream.start()
            logger.info("Audio capture started (device=%s, rate=%d Hz)", self.device, self.sample_rate)

            while self._running:
                # stream.read() blocks ~30ms waiting for samples — run it in a
                # worker thread so the asyncio event loop (and the websocket
                # send/listen tasks) keep running.
                data, overflow = await asyncio.to_thread(
                    self._stream.read, self.blocksize
                )
                if overflow:
                    logger.warning("Audio buffer overflow")

                # While paused, drain the stream but don't send anything —
                # the hotkey controls when audio reaches the server.
                if self._paused:
                    continue

                try:
                    self._queue.put_nowait(data.tobytes())
                except asyncio.QueueFull:
                    logger.warning("Audio queue full, dropping frame")

        except Exception as e:
            logger.error("Audio capture error: %s", e)
            self._running = False
        finally:
            if self._stream:
                self._stream.stop()
                self._stream.close()
                logger.info("Audio capture stopped")

    def stop(self) -> None:
        """Stop audio capture."""
        self._running = False

    def set_paused(self, paused: bool) -> None:
        """Pause/resume enqueuing audio frames. The stream stays open so the
        device isn't re-initialized on every toggle — only the put_nowait is
        gated by this flag.
        """
        self._paused = paused

    @property
    def paused(self) -> bool:
        return self._paused

    @staticmethod
    def list_devices() -> None:
        """Print available audio devices."""
        print("\nAvailable audio input devices:")
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                print(f"  {i}: {device['name']} ({device['max_input_channels']} in, "
                      f"{device['default_samplerate']} Hz)")
        print()
