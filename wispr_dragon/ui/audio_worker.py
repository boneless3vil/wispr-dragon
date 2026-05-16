"""Audio capture worker thread for live recording."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AudioWorker:
    """Captures audio from microphone in a thread-safe manner.

    Emits audio chunks via callback, handles VAD segmentation.
    Designed to run in a separate thread.
    """

    def __init__(self, config, on_audio_chunk=None, on_error=None):
        """Initialize audio worker.

        Args:
            config: AudioConfig with sample_rate, channels, etc.
            on_audio_chunk: Callback when audio chunk is ready (receives numpy array)
            on_error: Callback on error (receives error message)
        """
        self.config = config
        self.on_audio_chunk = on_audio_chunk
        self.on_error = on_error
        self.is_running = False
        self.audio_stream = None
        self.vad = None

    def setup(self) -> bool:
        """Initialize audio capture and VAD.

        Returns:
            True on success, False on error
        """
        try:
            import sounddevice as sd
            import numpy as np
            from silero_vad import load_silero_vad

            # Initialize VAD
            self.vad = load_silero_vad()

            # Verify we can access microphone
            devices = sd.query_devices()
            if not devices:
                raise RuntimeError("No audio devices found")

            logger.info(
                "Audio setup: %dHz, %d channel(s), device=%s",
                self.config.sample_rate,
                self.config.channels,
                sd.default.device[0] if sd.default.device[0] is not None else "default",
            )
            return True

        except ImportError as e:
            msg = f"Missing audio dependencies: {e}. Install: pip install sounddevice silero-vad"
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)
            return False
        except Exception as e:
            msg = f"Audio setup failed: {e}"
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)
            return False

    def start_recording(self) -> bool:
        """Start capturing audio from microphone.

        Returns:
            True on success
        """
        if not self.setup():
            return False

        try:
            import sounddevice as sd
            import numpy as np

            self.is_running = True

            # Duration of each chunk (ms)
            chunk_duration_ms = 100
            chunk_size = int(self.config.sample_rate * chunk_duration_ms / 1000)

            logger.info("Starting audio capture (chunk_size=%d)", chunk_size)

            def audio_callback(indata, frames, time, status):
                """Called by sounddevice when audio data is ready."""
                if status:
                    logger.warning("Audio stream status: %s", status)

                chunk = indata[:, 0].copy()  # Get first channel

                # Emit to caller
                if self.on_audio_chunk and self.is_running:
                    self.on_audio_chunk(chunk)

            # Start recording stream
            self.audio_stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                blocksize=chunk_size,
                callback=audio_callback,
                latency="low",
            )

            self.audio_stream.start()
            logger.info("Audio capture started")
            return True

        except Exception as e:
            msg = f"Failed to start recording: {e}"
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)
            self.is_running = False
            return False

    def stop_recording(self):
        """Stop capturing audio."""
        self.is_running = False
        if self.audio_stream:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
                logger.info("Audio capture stopped")
            except Exception as e:
                logger.error("Error stopping audio: %s", e)
        self.audio_stream = None

    def cleanup(self):
        """Clean up resources."""
        self.stop_recording()
        self.vad = None
