"""Abstract base for transcription engines."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TranscriptionSegment:
    text: str
    start: float
    end: float
    confidence: float = 0.0
    words: list = field(default_factory=list)
    # Alternative transcription hypotheses (N-best), best-first, EXCLUDING the
    # chosen `text`. Empty today: faster-whisper/CTranslate2 don't expose beam
    # runners-up via their public API, and the cloud APIs return none. This is
    # the forward-compatible slot — a future custom decode can populate it and
    # the correction window will prefer it over synthesized alternates, with no
    # protocol change (the transcript message gains an optional field only when
    # it's actually non-empty).
    alternatives: list = field(default_factory=list)


@dataclass
class TranscriptionResult:
    text: str
    segments: list[TranscriptionSegment] = field(default_factory=list)
    language: str = "en"
    duration: float = 0.0


class TranscriptionEngine(ABC):
    """Abstract base class for speech-to-text engines."""

    @abstractmethod
    def load_model(self, model_size: str, device: str = "auto",
                   compute_type: str = "auto") -> None:
        """Load the transcription model."""

    @abstractmethod
    def transcribe(
        self,
        audio,
        language: str = "en",
        initial_prompt: str = "",
        hotwords: str = "",
        beam_size: int = 5,
    ) -> TranscriptionResult:
        """Transcribe audio data to text."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine backend is available."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this engine."""
