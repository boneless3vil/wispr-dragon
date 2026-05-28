"""Pipeline runner extracted from main.py for reuse in server mode."""

import logging
import numpy as np
from pathlib import Path

from wispr_dragon.config import Config
from wispr_dragon.correction.dictionary import UserDictionary
from wispr_dragon.correction.hotwords import HotwordManager
from wispr_dragon.correction.post_processor import PostProcessor
from wispr_dragon.engine import create_engine
from wispr_dragon.macros.macro_runner import MacroRunner
from wispr_dragon.modes.mode_manager import ModeManager, Mode
from wispr_dragon.output.text_injector import TextInjector

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Encapsulates the speech processing pipeline for reusable execution."""

    def __init__(self, config: Config):
        """Initialize pipeline with components.

        Args:
            config: Config object with engine, correction, security settings
        """
        self.config = config
        self.engine = None
        self.vad = None
        self.dictionary = None
        self.post_processor = None
        self.macro_runner = None
        self.mode_mgr = None
        self.hotword_mgr = None

    def load(self, vad_enabled: bool = True) -> bool:
        """Load all pipeline components (model, VAD, etc.).

        Args:
            vad_enabled: Whether to load Voice Activity Detector

        Returns:
            True if load successful, False otherwise
        """
        try:
            logger.info("Loading pipeline components...")

            # Initialize dictionary and hotwords
            self.dictionary = UserDictionary()
            self.hotword_mgr = HotwordManager(
                self.dictionary,
                self.config.correction.max_hotwords,
            )

            # Initialize post-processor
            self.post_processor = PostProcessor(
                self.dictionary,
                fuzzy_threshold=self.config.correction.fuzzy_match_score,
                auto_apply_threshold=self.config.correction.auto_apply_threshold,
            )

            # Initialize macro runner
            self.macro_runner = MacroRunner(self.config.user_dir)

            # Initialize mode manager
            self.mode_mgr = ModeManager(macro_runner=self.macro_runner)

            # Create and load engine
            self.engine = create_engine(self.config)
            logger.info("Loading model: %s", self.config.engine.model_size)
            self.engine.load_model(
                self.config.engine.model_size,
                device=self.config.engine.device,
                compute_type=self.config.engine.compute_type,
            )
            logger.info("Model loaded successfully")

            # Load VAD if enabled
            if vad_enabled:
                from wispr_dragon.audio.vad import VoiceActivityDetector
                self.vad = VoiceActivityDetector(
                    sample_rate=self.config.audio.sample_rate,
                    threshold=self.config.audio.vad_threshold,
                    silence_duration_ms=self.config.audio.silence_duration_ms,
                    min_speech_duration_ms=self.config.audio.min_speech_duration_ms,
                )
                self.vad.load()
                logger.info("VAD loaded")

            return True

        except Exception as e:
            logger.error("Failed to load pipeline: %s", e)
            return False

    def process(self, audio: np.ndarray) -> str:
        """Process audio chunk through VAD and transcription.

        Args:
            audio: numpy array of float32 audio samples

        Returns:
            Transcribed text string, or empty string if nothing detected
        """
        if not self.engine:
            logger.error("Pipeline not loaded")
            return ""

        if not isinstance(audio, np.ndarray):
            return ""

        if audio.size == 0:
            return ""

        try:
            audio_data = audio

            if self.vad is not None:
                speech_segment = self.vad.process_chunk(audio)
                if speech_segment is None:
                    return ""
                audio_data = speech_segment
            else:
                audio_data = audio.flatten()

            if audio_data.size == 0:
                return ""

            result = self.engine.transcribe(
                audio_data,
                language=self.config.engine.language,
                initial_prompt=self.hotword_mgr.get_initial_prompt() if self.hotword_mgr else "",
                hotwords=self.hotword_mgr.get_hotwords() if self.hotword_mgr else "",
                beam_size=self.config.engine.beam_size,
            )

            if not result or not result.text.strip():
                return ""

            apply_formatting = self.mode_mgr.mode == Mode.DICTATION if self.mode_mgr else True
            processed = self.post_processor.process(result.text, apply_formatting=apply_formatting)

            return processed

        except Exception as e:
            logger.error("Error processing audio: %s", e)
            return ""

    def unload(self) -> None:
        """Cleanup resources."""
        if self.engine:
            self.engine = None
        if self.vad:
            self.vad = None
        logger.info("Pipeline unloaded")
