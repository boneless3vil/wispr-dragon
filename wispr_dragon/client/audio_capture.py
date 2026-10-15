"""Windows audio capture using sounddevice."""

import asyncio
import logging
import numpy as np
import sounddevice as sd
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Slots kept free in a bounded queue for control frames (utterance_start/end):
# audio is dropped first, so a burst of frames can never crowd out — or force
# the eviction of — the frames that delimit an utterance.
CONTROL_HEADROOM = 4


class WindowsAudioCapture:
    """Captures audio from Windows microphone and feeds to asyncio queue."""

    def __init__(
        self,
        sample_rate: int = 16000,
        device: Optional[int] = None,
        gate: Optional[Callable[[], bool]] = None,
    ):
        """Initialize audio capture.

        Args:
            sample_rate: Sample rate in Hz (default 16000 for Whisper)
            device: Device index, or None for default
            gate: Optional predicate; frames are only queued while it returns
                True. The client passes "is the server link up?" so audio is
                never buffered during an outage (it would be stale on reconnect).
        """
        self.sample_rate = sample_rate
        self.device = device
        self.channels = 1
        self.blocksize = 480  # 30ms at 16kHz
        self._stream = None
        self._running = False
        self._paused = False
        self._queue = None
        self._gate = gate
        # Why the last start() ended, if it was an error (device unplugged,
        # in use, missing). None after a clean stop(). The client reads it to
        # decide whether to retry opening the stream.
        self.error: Optional[str] = None
        self._dropped = 0

    async def start(self, queue: asyncio.Queue) -> None:
        """Start capturing audio and queueing to the provided asyncio queue.

        Returns when stop() is called or the stream fails; in the latter case
        ``self.error`` describes the failure.

        Args:
            queue: asyncio.Queue to put audio chunks into
        """
        self._queue = queue
        self._running = True
        self.error = None

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
                if self._paused or (self._gate is not None and not self._gate()):
                    continue

                self._enqueue(data.tobytes())

        except Exception as e:
            logger.error("Audio capture error: %s", e)
            self.error = str(e) or type(e).__name__
            self._running = False
        finally:
            stream, self._stream = self._stream, None
            if stream is not None:
                # A failed device can make stop()/close() raise too; that must
                # not mask the original error or escape to the caller.
                for op in (stream.stop, stream.close):
                    try:
                        op()
                    except Exception as e:
                        logger.debug("Ignoring audio stream cleanup error: %s", e)
                logger.info("Audio capture stopped")

    def _enqueue(self, frame: bytes) -> None:
        """Queue one frame; on a full queue drop it, warning once per burst.

        A bounded queue counts as full ``CONTROL_HEADROOM`` slots early, which
        are left for control frames.
        """
        queue = self._queue
        try:
            if queue.maxsize and queue.qsize() >= max(1, queue.maxsize - CONTROL_HEADROOM):
                raise asyncio.QueueFull
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            if self._dropped == 0:
                logger.warning("Audio queue full, dropping frames")
            self._dropped += 1
            return
        if self._dropped:
            logger.warning("Audio queue drained; %d frame(s) were dropped", self._dropped)
            self._dropped = 0

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
