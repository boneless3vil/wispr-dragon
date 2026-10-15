"""OpenAI API-based transcription backend.

Sends audio to OpenAI's hosted transcription endpoint (``whisper-1`` or any
other model name the API accepts, passed through from ``engine.model_size``).
Requires OPENAI_API_KEY environment variable.
"""

import io
import logging
import wave

import numpy as np

from .base import TranscriptionEngine, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

# Local faster-whisper size names mean nothing to the API (the shared config
# defaults to "small.en"); map them to the hosted Whisper model.
_LOCAL_MODEL_SIZES = {
    "tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
    "large", "large-v1", "large-v2", "large-v3", "large-v3-turbo", "turbo",
    "distil-large-v3",
}


def _api_model_name(model_size: str) -> str:
    if not model_size or model_size in _LOCAL_MODEL_SIZES:
        if model_size:
            logger.warning("model_size %r is a local Whisper size; using whisper-1", model_size)
        return "whisper-1"
    return model_size


def _to_wav(audio: np.ndarray, sample_rate: int = 16000) -> io.BytesIO:
    """16-bit mono WAV in memory — no ffmpeg/pydub needed, no gain change."""
    pcm = (np.clip(audio.astype(np.float32).ravel(), -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    buffer.seek(0)
    return buffer


class OpenAIAPIEngine(TranscriptionEngine):
    """Transcription engine using the OpenAI transcription API.

    Requires OPENAI_API_KEY environment variable.
    """

    def __init__(self):
        self._client = None
        self._model = None

    @property
    def name(self) -> str:
        return "openai-api"

    def is_available(self) -> bool:
        try:
            import openai  # noqa: F401
            import os
            api_key = os.getenv("OPENAI_API_KEY")
            return api_key is not None and api_key.startswith("sk-")
        except ImportError:
            return False

    def load_model(self, model_size: str = "whisper-1", device: str = "auto",
                   compute_type: str = "auto") -> None:
        import openai
        import os

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable not set. "
                "Get an API key from https://platform.openai.com/account/api-keys"
            )

        if not api_key.startswith("sk-"):
            raise ValueError(
                f"Invalid OPENAI_API_KEY format: must start with 'sk-', got '{api_key[:5]}...'. "
                "Check your API key at https://platform.openai.com/account/api-keys"
            )

        # A stalled request must not freeze the server's engine thread for the
        # SDK's 10-minute default.
        self._client = openai.OpenAI(api_key=api_key, timeout=30.0, max_retries=1)
        self._model = _api_model_name(model_size)
        logger.info("OpenAI API engine initialized with model=%s", self._model)

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "en",
        initial_prompt: str = "",
        hotwords: str = "",
        beam_size: int = 5,
    ) -> TranscriptionResult:
        if self._client is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        wav_buffer = _to_wav(audio)

        # Prepare prompt
        prompt = initial_prompt
        if hotwords:
            prompt = f"{hotwords}. {prompt}" if prompt else hotwords

        # Call OpenAI API
        transcript = self._client.audio.transcriptions.create(
            model=self._model,
            file=("audio.wav", wav_buffer, "audio/wav"),
            language=language,
            prompt=prompt or None,
            temperature=0.0,
            # Segment timings come only from whisper-1; the newer transcribe
            # models accept plain "json" only.
            response_format="verbose_json" if self._model == "whisper-1" else "json",
        )

        # Parse response
        segments = []
        for seg in getattr(transcript, "segments", None) or []:
            words = []
            if getattr(seg, "words", None):
                words = [
                    {
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "probability": getattr(w, "probability", 1.0),
                    }
                    for w in seg.words
                ]
            segments.append(TranscriptionSegment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=1.0,
                words=words,
            ))

        full_text = transcript.text.strip() if hasattr(transcript, "text") else ""

        return TranscriptionResult(
            text=full_text,
            segments=segments,
            language=language,
            duration=segments[-1].end if segments else 0.0,
        )
