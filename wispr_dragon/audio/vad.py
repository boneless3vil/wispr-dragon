"""Voice Activity Detection wrapper using Silero VAD."""

import logging
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
        self._buffered = 0  # samples in _speech_buffer
        self._residual = np.zeros(0, dtype=np.float32)  # <512-sample tail
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

        # Silero VAD scores exactly 512-sample windows at 16 kHz. Capture frames
        # rarely divide evenly (30 ms = 480 samples), so carry the remainder
        # into the next call instead of zero-padding: padding fed silence into
        # the speech buffer (and to Whisper) and broke up the RNN's input.
        chunk_size = 512
        audio = np.concatenate([self._residual, audio.astype(np.float32, copy=False)])
        usable = len(audio) // chunk_size * chunk_size
        self._residual = audio[usable:].copy()

        for i in range(0, usable, chunk_size):
            window = audio[i:i + chunk_size]
            confidence = self._model(torch.from_numpy(window), self.sample_rate).item()

            if confidence >= self.threshold:
                self._is_speaking = True
                self._silence_counter = 0
                self._speech_buffer.append(window)
                self._buffered += len(window)
            elif self._is_speaking:
                self._silence_counter += len(window)
                self._speech_buffer.append(window)
                self._buffered += len(window)

                if self._silence_counter >= self.silence_samples:
                    # Speech segment complete. Silero is a streaming RNN — its
                    # hidden state must be cleared between segments or the next
                    # one's confidence scores skew based on the previous segment.
                    segment = self._flush()
                    if len(segment) >= self.min_speech_samples:
                        # Windows after this one are scored on the next call.
                        self._residual = audio[i + chunk_size:].copy()
                        return segment

            # Guard against infinite buffer growth
            if self._buffered > self.max_buffer_samples and self._is_speaking:
                logger.warning("VAD buffer exceeded max size, flushing")
                segment = self._flush()
                if len(segment) >= self.min_speech_samples:
                    self._residual = audio[i + chunk_size:].copy()
                    return segment

        return None

    def _flush(self) -> np.ndarray:
        """Hand back the buffered segment and clear speech state."""
        segment = np.concatenate(self._speech_buffer)
        self._speech_buffer.clear()
        self._buffered = 0
        self._is_speaking = False
        self._silence_counter = 0
        self._model.reset_states()
        return segment

    def trim(self, audio: np.ndarray) -> Optional[np.ndarray]:
        """Trim leading/trailing silence from one complete utterance.

        Unlike :meth:`process_chunk`, this never splits the audio: it returns a
        single slice spanning the first speech onset to the last offset (padded
        by ``speech_pad_ms``), so a mid-sentence pause stays inside the result.
        That's what makes utterance-scoped transcription possible — the hotkey
        decides the boundary, the VAD only shaves the dead air off the ends.

        Returns:
            The trimmed float32 audio, or None if there's no speech (an
            accidental hotkey tap) or too little to be worth transcribing.
        """
        import torch

        if self._model is None:
            raise RuntimeError("VAD model not loaded. Call load() first.")

        if audio.ndim > 1:
            audio = audio.flatten()
        if audio.size == 0:
            return None

        # Silero is a streaming RNN: clear hidden state before and after so this
        # one-shot call neither inherits nor leaks state across utterances.
        self._model.reset_states()
        try:
            stamps = self._get_speech_timestamps(
                torch.from_numpy(audio).float(),
                self._model,
                sampling_rate=self.sample_rate,
                threshold=self.threshold,
            )
        finally:
            self._model.reset_states()

        if not stamps:
            return None

        start = max(0, stamps[0]["start"] - self.speech_pad_samples)
        end = min(len(audio), stamps[-1]["end"] + self.speech_pad_samples)
        segment = audio[start:end]
        if len(segment) < self.min_speech_samples:
            return None
        return segment

    def reset(self) -> None:
        """Reset the VAD state."""
        self._speech_buffer.clear()
        self._buffered = 0
        self._residual = np.zeros(0, dtype=np.float32)
        self._silence_counter = 0
        self._is_speaking = False
        if self._model is not None:
            self._model.reset_states()
