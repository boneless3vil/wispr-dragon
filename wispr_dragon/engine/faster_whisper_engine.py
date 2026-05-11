"""faster-whisper (CTranslate2) transcription backend."""

import logging
import numpy as np

from .base import TranscriptionEngine, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)


class FasterWhisperEngine(TranscriptionEngine):
    """Transcription engine using faster-whisper (CTranslate2).

    Best performance on CUDA and CPU. ROCm support depends on
    CTranslate2-ROCm community builds.
    """

    def __init__(self):
        self._model = None

    @property
    def name(self) -> str:
        return "faster-whisper"

    def is_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def load_model(self, model_size: str = "medium.en", device: str = "auto",
                   compute_type: str = "auto") -> None:
        from faster_whisper import WhisperModel

        if device == "auto":
            device = self._detect_device()
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        logger.info(
            "Loading faster-whisper model=%s device=%s compute_type=%s",
            model_size, device, compute_type,
        )
        self._model = WhisperModel(
            model_size, device=device, compute_type=compute_type,
        )

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

        segments_gen, info = self._model.transcribe(
            audio,
            language=language,
            initial_prompt=initial_prompt or None,
            hotwords=hotwords or None,
            beam_size=beam_size,
            word_timestamps=True,
            vad_filter=True,
        )

        segments = []
        full_text_parts = []
        for seg in segments_gen:
            words = []
            if seg.words:
                words = [
                    {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                    for w in seg.words
                ]
            segment = TranscriptionSegment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=seg.avg_logprob,
                words=words,
            )
            segments.append(segment)
            full_text_parts.append(seg.text.strip())

        return TranscriptionResult(
            text=" ".join(full_text_parts),
            segments=segments,
            language=info.language,
            duration=info.duration,
        )

    def _detect_device(self) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"
