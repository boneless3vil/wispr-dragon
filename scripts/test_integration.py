#!/usr/bin/env python3
"""Integration test: audio capture + VAD + transcription."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


def test_with_openai_api():
    """Test full pipeline with OpenAI API engine."""
    import os
    import numpy as np
    from wispr_dragon.config import Config
    from wispr_dragon.audio.capture import AudioCapture
    from wispr_dragon.audio.vad import VoiceActivityDetector
    from wispr_dragon.engine.openai_api_engine import OpenAIAPIEngine

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠ Skipping OpenAI API test (OPENAI_API_KEY not set)")
        return True

    print("\n--- Integration Test: OpenAI API Engine ---")
    try:
        engine = OpenAIAPIEngine()
        if not engine.is_available():
            print("✗ OpenAI API engine not available")
            return False

        print("✓ OpenAI API engine available")
        engine.load_model(model_size="whisper-1")
        print("✓ Model loaded (whisper-1)")

        # Simulate transcription with sample audio
        sample_audio = np.random.randn(16000).astype(np.float32) * 0.1

        result = engine.transcribe(
            sample_audio,
            language="en",
            initial_prompt="",
        )

        print(f"✓ Transcription completed")
        print(f"  Text: {result.text[:100] if result.text else '(empty)'}")
        print(f"  Duration: {result.duration:.2f}s")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_with_local_engine():
    """Test full pipeline with local transcription engine."""
    import numpy as np
    from wispr_dragon.config import Config
    from wispr_dragon.audio.capture import AudioCapture
    from wispr_dragon.audio.vad import VoiceActivityDetector
    from wispr_dragon.main import create_engine

    print("\n--- Integration Test: Local Transcription Engine ---")
    try:
        config = Config()
        engine = create_engine(config)

        print(f"✓ Engine created: {engine.name}")

        if not engine.is_available():
            print(f"✗ Engine {engine.name} not available")
            return False

        print(f"✓ Engine available, loading model...")
        engine.load_model(
            model_size=config.engine.model_size,
            device=config.engine.device,
            compute_type=config.engine.compute_type,
        )
        print(f"✓ Model loaded: {config.engine.model_size}")

        # Test with synthetic audio
        sample_audio = np.zeros(16000, dtype=np.float32)
        print("  Testing transcription with silence...")

        result = engine.transcribe(
            sample_audio,
            language="en",
        )

        print(f"✓ Transcription completed")
        print(f"  Text: '{result.text}'")
        print(f"  Language: {result.language}")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_audio_capture_integration():
    """Test audio capture with VAD."""
    import numpy as np
    from wispr_dragon.audio.capture import AudioCapture
    from wispr_dragon.audio.vad import VoiceActivityDetector

    print("\n--- Integration Test: Audio Capture + VAD ---")
    try:
        print("Loading VAD model...")
        vad = VoiceActivityDetector(
            sample_rate=16000,
            threshold=0.5,
            silence_duration_ms=500,
            min_speech_duration_ms=250,
        )
        vad.load()
        print("✓ VAD loaded")

        print("Starting audio capture (3 seconds)...")
        capture = AudioCapture(sample_rate=16000, channels=1, block_duration_ms=30)
        capture.start()

        speech_segments = 0
        silence_blocks = 0

        for i in range(100):
            chunk = capture.read(timeout=0.5)
            if chunk is None:
                silence_blocks += 1
                continue

            segment = vad.process_chunk(chunk)
            if segment is not None:
                speech_segments += 1

        capture.stop()

        print(f"✓ Audio capture completed")
        print(f"  Speech segments detected: {speech_segments}")
        print(f"  Silent blocks: {silence_blocks}")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("Wispr-Dragon Integration Tests")
    print("=" * 60)

    results = []

    # Test audio capture + VAD
    results.append(("Audio Capture + VAD", test_audio_capture_integration()))

    # Test local engine
    results.append(("Local Transcription Engine", test_with_local_engine()))

    # Test OpenAI API engine (if available)
    results.append(("OpenAI API Engine", test_with_openai_api()))

    print("\n" + "=" * 60)
    print("Integration Test Summary:")
    print("=" * 60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
