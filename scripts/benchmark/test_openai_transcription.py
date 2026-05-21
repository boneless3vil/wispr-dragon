#!/usr/bin/env python3
"""Test OpenAI Whisper API transcription with Wispr Dragon."""

import os
import sys
import time
import numpy as np
from pathlib import Path

def test_openai_api():
    """Test OpenAI API transcription with audio from microphone."""
    from wispr_dragon.audio.capture import AudioCapture
    from wispr_dragon.engine.openai_api_engine import OpenAIAPIEngine

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        print("\nTo set it, run:")
        print("  export OPENAI_API_KEY='sk-your-key-here'")
        return False

    print("\n" + "=" * 60)
    print("Testing OpenAI Whisper API with Wispr Dragon")
    print("=" * 60)

    try:
        # Initialize engine
        print("\n1. Initializing OpenAI API engine...")
        engine = OpenAIAPIEngine()
        engine.load_model(model_size="whisper-1")
        print("   ✓ Engine initialized")

        # Start audio capture
        print("\n2. Starting audio capture (5 seconds)...")
        print("   Speak clearly into your microphone...")
        capture = AudioCapture(sample_rate=16000, channels=1)
        capture.start()

        # Collect audio
        audio_data = []
        for i in range(166):  # ~5 seconds at 30ms blocks
            chunk = capture.read(timeout=0.5)
            if chunk is not None:
                audio_data.append(chunk)
                # Progress indicator
                if (i + 1) % 33 == 0:
                    print(f"   Captured {(i+1)*30//1000} seconds...")

        capture.stop()
        print("   ✓ Audio capture complete")

        if not audio_data:
            print("   ✗ No audio data captured")
            return False

        # Combine audio chunks
        audio = np.concatenate(audio_data)
        print(f"   Audio shape: {audio.shape}")

        # Check audio levels
        peak = np.max(np.abs(audio))
        rms = np.sqrt(np.mean(audio ** 2))
        print(f"   Peak level: {peak:.6f}")
        print(f"   RMS level: {rms:.6f}")

        if peak < 0.001:
            print("   ⚠ WARNING: Very low audio levels - try speaking louder")

        # Transcribe
        print("\n3. Transcribing audio with OpenAI API...")
        result = engine.transcribe(audio, language="en")

        print("\n" + "=" * 60)
        print("TRANSCRIPTION RESULT")
        print("=" * 60)
        print(f"Text: {result.text}")
        if result.segments:
            print(f"Confidence: {result.segments[0].confidence:.2%}")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_openai_api()
    sys.exit(0 if success else 1)
