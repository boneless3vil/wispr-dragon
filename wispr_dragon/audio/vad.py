"""Voice Activity Detection wrapper using Silero VAD."""

import logging
from collections import deque
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """Detects speech segments in audio using Silero VAD.

    Buffers audio and emits complete speech segments when silence
    is detected after speech.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        silence_duration_ms: int = 500,
        min_speech_duration_ms: int = 250,
        speech_pad_ms: int = 100,
        max_buffer_seconds: int = 30,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.silence_samples = int(sample_rate * silence_duration_ms / 1000)
        self.min_speech_samples = int(sample_rate * min_speech_duration_ms / 1000)
        self.speech_pad_samples = int(sample_rate * speech_pad_ms / 1000)
        self.max_buffer_samples = int(sample_rate * max_buffer_seconds)

        self._model = None
        self._speech_buffer: list[np.ndarray] = []
        self._silence_counter = 0
        self._is_speaking = False

    def load(self) -> None:
        """Load the Silero VAD model."""
        import torch

        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        self._model = model
        self._get_speech_timestamps = utils[0]
        logger.info("Silero VAD model loaded")

    def process_chunk(self, audio: np.ndarray) -> Optional[np.ndarray]:
        """Process an audio chunk and return a complete speech segment if ready.

        Args:
            audio: Float32 audio array, shape (samples,) or (samples, 1)

        Returns:
            Complete speech segment as float32 array, or None if still collecting.
        """
        import torch

        if self._model is None:
            raise RuntimeError("VAD model not loaded. Call load() first.")

        # Flatten to 1D
        if audio.ndim > 1:
            audio = audio.flatten()

        # Silero VAD expects 512-sample chunks at 16kHz
        tensor = torch.from_numpy(audio).float()
        # Process in 512-sample windows
        chunk_size = 512
        for i in range(0, len(tensor), chunk_size):
            window = tensor[i:i + chunk_size]
            if len(window) < chunk_size:
                window = torch.nn.functional.pad(window, (0, chunk_size - len(window)))

            confidence = self._model(window, self.sample_rate).item()

            if confidence >= self.threshold:
                self._is_speaking = True
                self._silence_counter = 0
                self._speech_buffer.append(window.numpy())
            elif self._is_speaking:
                self._silence_counter += len(window)
                self._speech_buffer.append(window.numpy())

                if self._silence_counter >= self.silence_samples:
                    # Speech segment complete. Silero is a streaming RNN — its
                    # hidden state must be cleared between segments or the next
                    # one's confidence scores skew based on the previous segment.
                    segment = np.concatenate(self._speech_buffer)
                    self._speech_buffer.clear()
                    self._is_speaking = False
                    self._silence_counter = 0
                    self._model.reset_states()

                    if len(segment) >= self.min_speech_samples:
                        return segment

            # Guard against infinite buffer growth
            buffer_size = sum(len(chunk) for chunk in self._speech_buffer)
            if buffer_size > self.max_buffer_samples and self._is_speaking:
                logger.warning("VAD buffer exceeded max size, flushing")
                segment = np.concatenate(self._speech_buffer)
                self._speech_buffer.clear()
                self._is_speaking = False
                self._silence_counter = 0
                self._model.reset_states()
                if len(segment) >= self.min_speech_samples:
                    return segment

        return None

    def reset(self) -> None:
        """Reset the VAD state."""
        self._speech_buffer.clear()
        self._silence_counter = 0
        self._is_speaking = False
        if self._model is not None:
            self._model.reset_states()
