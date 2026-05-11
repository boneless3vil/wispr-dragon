"""OpenAI Whisper (PyTorch) transcription backend.

This backend works with ROCm, CUDA, and CPU via PyTorch.
Slower than faster-whisper but more compatible with AMD GPUs.
"""

import logging
import numpy as np

from .base import TranscriptionEngine, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)


class OpenAIWhisperEngine(TranscriptionEngine):
    """Transcription engine using the original Whisper model (PyTorch).

    Best compatibility with ROCm/AMD GPUs since it uses PyTorch directly.
    """

    def __init__(self):
        self._model = None
        self._device = None

    @property
    def name(self) -> str:
        return "openai-whisper"

    def is_available(self) -> bool:
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def load_model(self, model_size: str = "medium.en", device: str = "auto",
                   compute_type: str = "auto") -> None:
        import whisper
        import torch

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        self._device = device
        logger.info(
            "Loading openai-whisper model=%s device=%s", model_size, device,
        )
        self._model = whisper.load_model(model_size, device=device)

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "en",
        initial_prompt: str = "",
        hotwords: str = "",
        beam_size: int = 5,
    ) -> TranscriptionResult:
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        # openai-whisper does not support hotwords directly;
        # we fold them into the initial_prompt instead
        prompt = initial_prompt
        if hotwords:
            prompt = f"{hotwords}. {prompt}" if prompt else hotwords

        result = self._model.transcribe(
            audio,
            language=language,
            initial_prompt=prompt or None,
            beam_size=beam_size,
            word_timestamps=True,
        )

        segments = []
        for seg in result.get("segments", []):
            words = []
            if "words" in seg:
                words = [
                    {"word": w["word"], "start": w["start"], "end": w["end"],
                     "probability": w.get("probability", 0.0)}
                    for w in seg["words"]
                ]
            segment = TranscriptionSegment(
                text=seg["text"].strip(),
                start=seg["start"],
                end=seg["end"],
                confidence=seg.get("avg_logprob", 0.0),
                words=words,
            )
            segments.append(segment)

        full_text = result.get("text", "").strip()
        return TranscriptionResult(
            text=full_text,
            segments=segments,
            language=result.get("language", language),
            duration=segments[-1].end if segments else 0.0,
        )
