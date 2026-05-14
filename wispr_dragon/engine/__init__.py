"""Transcription engine factory and loader."""

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import TranscriptionEngine

from .base import TranscriptionEngine

logger = logging.getLogger(__name__)


def create_engine(config) -> TranscriptionEngine:
    """Create the appropriate transcription engine based on config and availability.

    Args:
        config: Config object with engine settings

    Returns:
        TranscriptionEngine instance

    Raises:
        SystemExit: If no suitable engine is found
    """
    backend = config.engine.backend

    if backend == "auto":
        return _create_auto_engine()
    elif backend == "faster-whisper":
        from .faster_whisper_engine import FasterWhisperEngine
        return FasterWhisperEngine()
    elif backend == "openai-whisper":
        from .openai_whisper_engine import OpenAIWhisperEngine
        return OpenAIWhisperEngine()
    elif backend == "openai-api":
        from .openai_api_engine import OpenAIAPIEngine
        return OpenAIAPIEngine()
    else:
        logger.error("Unknown engine backend: %s", backend)
        sys.exit(1)


def _create_auto_engine() -> TranscriptionEngine:
    """Auto-detect and create the best available transcription engine."""
    try:
        import torch
        has_amd_gpu = hasattr(torch.version, 'hip') and torch.version.hip
        if has_amd_gpu:
            from .openai_whisper_engine import OpenAIWhisperEngine
            engine = OpenAIWhisperEngine()
            if engine.is_available():
                logger.info("AMD GPU detected - using openai-whisper engine for ROCm support")
                return engine
    except ImportError:
        pass

    from .faster_whisper_engine import FasterWhisperEngine
    engine = FasterWhisperEngine()
    if engine.is_available():
        logger.info("Using faster-whisper engine")
        return engine

    from .openai_whisper_engine import OpenAIWhisperEngine
    engine = OpenAIWhisperEngine()
    if engine.is_available():
        logger.info("Using openai-whisper engine (fallback)")
        return engine

    from .openai_api_engine import OpenAIAPIEngine
    engine = OpenAIAPIEngine()
    if engine.is_available():
        logger.info("Using openai-api engine (fallback)")
        return engine

    logger.error("No transcription engine available. Install faster-whisper, openai-whisper, or set OPENAI_API_KEY.")
    sys.exit(1)


__all__ = ["create_engine", "TranscriptionEngine"]
