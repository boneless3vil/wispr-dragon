"""Wispr-Dragon main entry point."""

import argparse
import logging
import signal
import sys

import numpy as np

from .config import Config
from .correction.dictionary import UserDictionary
from .correction.hotwords import HotwordManager
from .correction.post_processor import PostProcessor
from .modes.mode_manager import ModeManager, Mode
from .output.text_injector import TextInjector

logger = logging.getLogger("wispr_dragon")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_engine(config: Config):
    """Create the appropriate transcription engine based on config and availability."""
    backend = config.engine.backend

    if backend == "auto":
        # Try faster-whisper first, fall back to openai-whisper, then openai-api
        from .engine.faster_whisper_engine import FasterWhisperEngine
        engine = FasterWhisperEngine()
        if engine.is_available():
            logger.info("Using faster-whisper engine")
            return engine

        from .engine.openai_whisper_engine import OpenAIWhisperEngine
        engine = OpenAIWhisperEngine()
        if engine.is_available():
            logger.info("Using openai-whisper engine (fallback)")
            return engine

        from .engine.openai_api_engine import OpenAIAPIEngine
        engine = OpenAIAPIEngine()
        if engine.is_available():
            logger.info("Using openai-api engine (fallback)")
            return engine

        logger.error("No transcription engine available. Install faster-whisper, openai-whisper, or set OPENAI_API_KEY.")
        sys.exit(1)

    elif backend == "faster-whisper":
        from .engine.faster_whisper_engine import FasterWhisperEngine
        return FasterWhisperEngine()

    elif backend == "openai-whisper":
        from .engine.openai_whisper_engine import OpenAIWhisperEngine
        return OpenAIWhisperEngine()

    elif backend == "openai-api":
        from .engine.openai_api_engine import OpenAIAPIEngine
        return OpenAIAPIEngine()

    else:
        logger.error("Unknown engine backend: %s", backend)
        sys.exit(1)


def create_audio_source(config: Config):
    """Create the appropriate audio capture source."""
    if config.audio.source == "network":
        from .audio.capture import NetworkAudioCapture
        return NetworkAudioCapture(
            host=config.audio.network_host,
            port=config.audio.network_port,
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )
    else:
        from .audio.capture import AudioCapture
        return AudioCapture(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )


def main():
    parser = argparse.ArgumentParser(description="Wispr-Dragon Speech Recognition")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--model", type=str, help="Override model size (e.g., small.en, medium.en, large-v3)")
    parser.add_argument("--device", type=str, help="Override device (cuda, cpu)")
    parser.add_argument("--no-vad", action="store_true", help="Disable voice activity detection")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger.info("Wispr-Dragon starting...")

    # Load config
    config = Config.load()
    if args.model:
        config.engine.model_size = args.model
    if args.device:
        config.engine.device = args.device

    # Initialize components
    dictionary = UserDictionary()
    hotword_mgr = HotwordManager(dictionary, config.correction.max_hotwords)
    post_processor = PostProcessor(
        dictionary,
        fuzzy_threshold=config.correction.fuzzy_match_score,
        auto_apply_threshold=config.correction.auto_apply_threshold,
    )
    mode_mgr = ModeManager()
    injector = TextInjector()

    # Load command grammar
    from .modes.command_mode import load_commands
    load_commands()

    # Create and load engine
    engine = create_engine(config)
    logger.info("Loading model: %s", config.engine.model_size)
    engine.load_model(
        config.engine.model_size,
        device=config.engine.device,
        compute_type=config.engine.compute_type,
    )
    logger.info("Model loaded successfully")

    # Create audio source
    audio_source = create_audio_source(config)

    # Set up VAD
    vad = None
    if not args.no_vad:
        from .audio.vad import VoiceActivityDetector
        vad = VoiceActivityDetector(
            sample_rate=config.audio.sample_rate,
            threshold=config.audio.vad_threshold,
            silence_duration_ms=config.audio.silence_duration_ms,
            min_speech_duration_ms=config.audio.min_speech_duration_ms,
        )
        vad.load()
        logger.info("VAD loaded")

    # Register mode handlers
    def handle_undo(text):
        injector.undo(text)

    def handle_correction(text, args=None):
        from .ui.correction_window import CorrectionWindow
        window = CorrectionWindow(dictionary)
        window.show(text)

    def handle_keystroke(text, args=None):
        import subprocess
        keys = args.get("keys", "") if args else ""
        if keys:
            subprocess.run(["xdotool", "key", "--clearmodifiers", keys], timeout=2)

    mode_mgr.register_handler("undo_last", handle_undo)
    mode_mgr.register_handler("open_correction_window", handle_correction)
    mode_mgr.register_handler("keystroke", handle_keystroke)

    # Signal handling
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False
        logger.info("Shutting down...")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Main loop
    logger.info("Ready. Listening... (Ctrl+C to quit)")
    audio_source.start()

    try:
        while running:
            chunk = audio_source.read(timeout=0.5)
            if chunk is None:
                continue

            if vad is not None:
                speech_segment = vad.process_chunk(chunk)
                if speech_segment is None:
                    continue
                audio_data = speech_segment
            else:
                audio_data = chunk.flatten()

            # Transcribe
            result = engine.transcribe(
                audio_data,
                language=config.engine.language,
                initial_prompt=hotword_mgr.get_initial_prompt(),
                hotwords=hotword_mgr.get_hotwords(),
                beam_size=config.engine.beam_size,
            )

            if not result.text.strip():
                continue

            # Post-process
            apply_formatting = mode_mgr.mode == Mode.DICTATION
            processed = post_processor.process(result.text, apply_formatting=apply_formatting)

            # Handle through mode manager
            output = mode_mgr.process_text(processed)
            if output:
                injector.inject(output + " ")
                logger.debug("Output: %s", output)

    finally:
        audio_source.stop()
        logger.info("Wispr-Dragon stopped")


if __name__ == "__main__":
    main()
