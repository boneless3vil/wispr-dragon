"""Audio capture from microphone with voice activity detection."""

import logging
import queue
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures audio from the microphone using sounddevice.

    Supports PulseAudio (WSL2/Linux native) and falls back to
    network streaming if direct capture fails.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        block_duration_ms: int = 30,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_duration_ms = block_duration_ms
        self.block_size = int(sample_rate * block_duration_ms / 1000)
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None
        self._running = False

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio callback status: %s", status)
        self._audio_queue.put(indata.copy())

    def start(self) -> None:
        import sounddevice as sd

        logger.info(
            "Starting audio capture: rate=%d channels=%d block=%dms",
            self.sample_rate, self.channels, self.block_duration_ms,
        )

        # Verify we have input devices
        try:
            devices = sd.query_devices()
            input_devices = [d for d in devices if d["max_input_channels"] > 0]
            if not input_devices:
                raise RuntimeError(
                    "No input devices found. Check microphone connection."
                )
            logger.debug("Found %d input device(s)", len(input_devices))
        except Exception as e:
            logger.error("Failed to query audio devices: %s", e)
            raise

        self._running = True
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._audio_callback,
            )
            self._stream.start()
            logger.info("Audio stream initialized and running")
        except Exception as e:
            self._running = False
            logger.error("Failed to start audio stream: %s", e)
            raise

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_running(self) -> bool:
        return self._running

    @staticmethod
    def list_devices():
        import sounddevice as sd
        return sd.query_devices()


class NetworkAudioCapture:
    """Receive audio streamed from a Windows-side capture server over TCP.

    Use this as a fallback when WSL2 PulseAudio passthrough is unreliable.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9876,
        sample_rate: int = 16000,
        channels: int = 1,
    ):
        self.host = host
        self.port = port
        self.sample_rate = sample_rate
        self.channels = channels
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _receive_loop(self):
        import socket

        bytes_per_sample = 2  # int16
        chunk_samples = int(self.sample_rate * 0.03)  # 30ms chunks
        chunk_bytes = chunk_samples * self.channels * bytes_per_sample

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(1)
            sock.settimeout(1.0)
            logger.info("Network audio server listening on %s:%d", self.host, self.port)

            while self._running:
                try:
                    conn, addr = sock.accept()
                except OSError:
                    continue
                logger.info("Audio client connected from %s", addr)
                buffer = b""
                with conn:
                    while self._running:
                        try:
                            data = conn.recv(chunk_bytes * 4)
                        except OSError:
                            break
                        if not data:
                            break
                        buffer += data
                        while len(buffer) >= chunk_bytes:
                            chunk = buffer[:chunk_bytes]
                            buffer = buffer[chunk_bytes:]
                            audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                            self._audio_queue.put(audio.reshape(-1, self.channels))

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def read(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_running(self) -> bool:
        return self._running
