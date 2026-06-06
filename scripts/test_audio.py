#!/usr/bin/env python3
"""Test microphone audio capture and VAD in WSL2."""

import sys


def test_audio_capture():
    """Test AudioCapture class initialization and streaming."""
    from wispr_dragon.audio.capture import AudioCapture
    import numpy as np

    print("\n--- Testing AudioCapture ---")
    try:
        capture = AudioCapture(sample_rate=16000, channels=1, block_duration_ms=30)
        print("✓ AudioCapture initialized")

        capture.start()
        print("✓ Audio stream started")

        # Collect audio for 2 seconds
        total_samples = 0
        max_level = 0
        rms_sum = 0
        chunk_count = 0

        for _ in range(67):  # ~2 seconds at 30ms blocks
            chunk = capture.read(timeout=0.5)
            if chunk is None:
                continue

            total_samples += chunk.shape[0]
            chunk_max = np.max(np.abs(chunk))
            max_level = max(max_level, chunk_max)
            rms_sum += np.sqrt(np.mean(chunk ** 2))
            chunk_count += 1

        capture.stop()
        print("✓ Audio stream stopped")

        if chunk_count > 0:
            avg_rms = rms_sum / chunk_count
            print(f"  Captured {total_samples} samples ({chunk_count} chunks)")
            print(f"  Peak level:  {max_level:.4f}")
            print(f"  Avg RMS:     {avg_rms:.6f}")

            if max_level < 0.001:
                print("  ⚠ WARNING: Very low audio level")
                return False

            return True
        else:
            print("  ✗ No audio data received")
            return False

    except Exception as e:
        print(f"✗ Error during AudioCapture: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_vad():
    """Test Voice Activity Detection."""
    from wispr_dragon.audio.vad import VoiceActivityDetector
    from wispr_dragon.audio.capture import AudioCapture

    print("\n--- Testing Voice Activity Detection ---")
    try:
        vad = VoiceActivityDetector(
            sample_rate=16000,
            threshold=0.5,
            silence_duration_ms=500,
            min_speech_duration_ms=250,
        )
        vad.load()
        print("✓ VAD model loaded")

        capture = AudioCapture(sample_rate=16000, channels=1, block_duration_ms=30)
        capture.start()
        print("✓ Audio stream started")
        print("  Listening for speech (3 seconds)...")

        speech_segments = 0
        for i in range(100):
            chunk = capture.read(timeout=0.5)
            if chunk is None:
                continue

            segment = vad.process_chunk(chunk)
            if segment is not None:
                speech_segments += 1

        capture.stop()
        print("✓ Audio stream stopped")
        print(f"  Detected {speech_segments} speech segments")

        return True

    except Exception as e:
        print(f"✗ Error during VAD test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sounddevice():
    """Test sounddevice availability and devices."""
    print("\n--- Testing sounddevice ---")
    try:
        import sounddevice as sd
        print("✓ sounddevice module imported")

        devices = sd.query_devices()
        input_devices = [d for d in devices if d["max_input_channels"] > 0]
        print(f"✓ Found {len(input_devices)} input device(s)")

        default = sd.default.device
        print(f"  Default input: {default[0]} (device {default[0] if isinstance(default, tuple) else default})")

        return len(input_devices) > 0

    except Exception as e:
        print(f"✗ Error with sounddevice: {e}")
        return False


def main():
    print("=" * 60)
    print("Wispr-Dragon Audio Initialization & Testing")
    print("=" * 60)

    results = []

    # Test sounddevice availability
    results.append(("sounddevice", test_sounddevice()))

    # Test AudioCapture
    results.append(("AudioCapture", test_audio_capture()))

    # Test VAD
    results.append(("Voice Activity Detection", test_vad()))

    print("\n" + "=" * 60)
    print("Test Summary:")
    print("=" * 60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n✓ All audio tests passed! Ready to transcribe.")
        return 0
    else:
        print("\n✗ Some tests failed. Troubleshooting:")
        if not results[0][1]:
            print("  - Install sounddevice: pip install sounddevice")
        if not results[1][1]:
            print("  - Check microphone: parecord --format=s16le --rate=16000 test.wav")
        if not results[2][1]:
            print("  - Download VAD model: python -c 'from silero_vad import load_silero_vad; load_silero_vad()'")
        return 1


if __name__ == "__main__":
    sys.exit(main())
