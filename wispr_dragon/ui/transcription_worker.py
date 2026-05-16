"""Transcription worker thread for real-time speech-to-text."""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class TranscriptionWorker:
    """Processes audio chunks and runs transcription engine.

    Maintains streaming context, emits live hypothesis + final results.
    Designed to run in a separate thread.
    """

    def __init__(self, engine, post_processor=None, on_transcription=None, on_error=None):
        """Initialize transcription worker.

        Args:
            engine: TranscriptionEngine instance (e.g., FasterWhisperEngine)
            post_processor: PostProcessor for text correction (optional)
            on_transcription: Callback when transcription updates (receives live, final)
            on_error: Callback on error (receives error message)
        """
        self.engine = engine
        self.post_processor = post_processor
        self.on_transcription = on_transcription
        self.on_error = on_error

        self.audio_buffer = np.array([], dtype=np.float32)
        self.buffer_max_seconds = 30  # Cap to prevent unbounded growth
        self.sample_rate = 16000
        self.is_processing = False

    def process_audio_chunk(self, chunk: np.ndarray):
        """Add audio chunk to buffer and process.

        Args:
            chunk: Audio data as numpy array (float32 or int16)
        """
        try:
            # Convert to float32 if needed
            if chunk.dtype != np.float32:
                chunk = chunk.astype(np.float32) / 32768.0  # int16 normalization

            # Add to buffer
            self.audio_buffer = np.concatenate([self.audio_buffer, chunk])

            # Cap buffer size to prevent unbounded growth
            max_buffer_samples = int(self.buffer_max_seconds * self.sample_rate)
            if len(self.audio_buffer) > max_buffer_samples:
                logger.warning(
                    "Audio buffer exceeded %.1f seconds, truncating",
                    self.buffer_max_seconds,
                )
                # Keep only the most recent chunk
                trim_size = len(self.audio_buffer) - max_buffer_samples
                self.audio_buffer = self.audio_buffer[trim_size:]

            # Process if we have enough audio (e.g., 1 second)
            if len(self.audio_buffer) >= self.sample_rate:
                self._process_buffer()

        except Exception as e:
            msg = f"Error processing audio chunk: {e}"
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)

    def _process_buffer(self):
        """Run transcription on current buffer."""
        try:
            if not self.is_processing:
                self.is_processing = True

                # Transcribe
                result = self.engine.transcribe(self.audio_buffer)
                text = result.get("text", "").strip() if result else ""

                # Post-process if available
                if self.post_processor and text:
                    text = self.post_processor.process(text)

                # Emit result
                if self.on_transcription:
                    self.on_transcription(live=text, final=None)

                self.is_processing = False

        except Exception as e:
            msg = f"Transcription error: {e}"
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)
            self.is_processing = False

    def flush_and_finalize(self) -> Optional[str]:
        """Process any remaining audio and finalize transcription.

        Returns:
            Final transcribed text, or None on error
        """
        try:
            if len(self.audio_buffer) == 0:
                return None

            logger.info("Finalizing transcription with %.1f seconds of audio",
                       len(self.audio_buffer) / self.sample_rate)

            result = self.engine.transcribe(self.audio_buffer)
            text = result.get("text", "").strip() if result else ""

            # Post-process
            if self.post_processor and text:
                text = self.post_processor.process(text)

            # Clear buffer
            self.audio_buffer = np.array([], dtype=np.float32)

            if self.on_transcription:
                self.on_transcription(live="", final=text)

            return text

        except Exception as e:
            msg = f"Finalization error: {e}"
            logger.error(msg)
            if self.on_error:
                self.on_error(msg)
            return None

    def reset(self):
        """Clear buffer and reset state."""
        self.audio_buffer = np.array([], dtype=np.float32)
        self.is_processing = False
