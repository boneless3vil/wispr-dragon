"""OpenAI API-based Whisper transcription backend.

Supports OpenAI's cloud Whisper API, including the latest GPT 5.5 model.
Requires OPENAI_API_KEY environment variable.
"""

import logging
from typing import Optional

import numpy as np

from .base import TranscriptionEngine, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)


class OpenAIAPIEngine(TranscriptionEngine):
    """Transcription engine using the OpenAI Whisper API.

    Supports all models available via the API, including GPT 5.5.
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
            import openai
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

        self._client = openai.OpenAI(api_key=api_key)
        self._model = model_size
        logger.info("OpenAI API engine initialized with model=%s", model_size)

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

        import io
        from pydub import AudioSegment

        # Convert numpy array to MP3 bytes for API
        audio_int16 = np.int16(audio / np.max(np.abs(audio)) * 32767)
        audio_bytes = audio_int16.tobytes()

        audio_segment = AudioSegment(
            data=audio_bytes,
            sample_width=2,
            frame_rate=16000,
            channels=1,
        )

        mp3_buffer = io.BytesIO()
        audio_segment.export(mp3_buffer, format="mp3")
        mp3_buffer.seek(0)

        # Prepare prompt
        prompt = initial_prompt
        if hotwords:
            prompt = f"{hotwords}. {prompt}" if prompt else hotwords

        # Call OpenAI API
        transcript = self._client.audio.transcriptions.create(
            model=self._model,
            file=("audio.mp3", mp3_buffer, "audio/mpeg"),
            language=language,
            prompt=prompt or None,
            temperature=0.0,
            response_format="verbose_json",
        )

        # Parse response
        segments = []
        if hasattr(transcript, "segments"):
            for seg in transcript.segments:
                words = []
                if hasattr(seg, "words"):
                    words = [
                        {
                            "word": w.word,
                            "start": w.start,
                            "end": w.end,
                            "probability": getattr(w, "probability", 1.0),
                        }
                        for w in seg.words
                    ]
                segment = TranscriptionSegment(
                    text=seg.text.strip(),
                    start=seg.start,
                    end=seg.end,
                    confidence=1.0,
                    words=words,
                )
                segments.append(segment)

        full_text = transcript.text.strip() if hasattr(transcript, "text") else ""

        return TranscriptionResult(
            text=full_text,
            segments=segments,
            language=language,
            duration=segments[-1].end if segments else 0.0,
        )
