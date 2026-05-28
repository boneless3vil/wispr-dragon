#!/usr/bin/env python3
"""Benchmark local Whisper vs OpenAI API for transcription speed."""

import os
import sys
import time
import numpy as np
from pathlib import Path

def capture_audio(duration_seconds=5):
    """Capture audio from microphone."""
    from wispr_dragon.audio.capture import AudioCapture

    print(f"\nRecording {duration_seconds} seconds of audio...")
    capture = AudioCapture(sample_rate=16000, channels=1)
    capture.start()

    audio_data = []
    num_chunks = int(duration_seconds * 1000 / 30)  # 30ms chunks

    for i in range(num_chunks):
        chunk = capture.read(timeout=0.5)
        if chunk is not None:
            audio_data.append(chunk)
        if (i + 1) % 33 == 0:
            print(f"  {(i+1)*30//1000}s recorded...")

    capture.stop()

    if not audio_data:
        print("ERROR: No audio captured")
        return None

    audio = np.concatenate(audio_data).squeeze()  # Flatten to 1D
    peak = np.max(np.abs(audio))
    rms = np.sqrt(np.mean(audio ** 2))

    print(f"✓ Audio captured: {audio.shape[0]} samples")
    print(f"  Peak: {peak:.4f}, RMS: {rms:.6f}")

    return audio

def benchmark_local_whisper(audio):
    """Benchmark local Faster-Whisper engine."""
    print("\n" + "=" * 60)
    print("LOCAL WHISPER (Faster-Whisper)")
    print("=" * 60)

    try:
        from wispr_dragon.engine.faster_whisper_engine import FasterWhisperEngine

        print("Loading model (small.en)...")
        start_load = time.time()
        engine = FasterWhisperEngine()
        engine.load_model(model_size='small.en')
        load_time = time.time() - start_load
        print(f"✓ Model loaded in {load_time:.2f}s")

        print("Transcribing audio...")
        start_transcribe = time.time()
        result = engine.transcribe(audio, language='en')
        transcribe_time = time.time() - start_transcribe
        print(f"✓ Transcription complete in {transcribe_time:.2f}s")

        total_time = load_time + transcribe_time

        print("\nRESULTS:")
        print(f"  Text: {result.text}")
        if result.segments:
            print(f"  Confidence: {result.segments[0].confidence:.2%}")
        print(f"\nTIMING:")
        print(f"  Model load:  {load_time:.2f}s (one-time)")
        print(f"  Transcribe:  {transcribe_time:.2f}s")
        print(f"  TOTAL:       {total_time:.2f}s")

        return {
            'name': 'Local Whisper',
            'text': result.text,
            'load_time': load_time,
            'transcribe_time': transcribe_time,
            'total_time': total_time,
        }

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def benchmark_openai_api(audio):
    """Benchmark OpenAI API engine."""
    print("\n" + "=" * 60)
    print("OPENAI API (Cloud Whisper)")
    print("=" * 60)

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("✗ OPENAI_API_KEY not set - skipping")
        return None

    try:
        from wispr_dragon.engine.openai_api_engine import OpenAIAPIEngine

        print("Initializing API engine...")
        start_init = time.time()
        engine = OpenAIAPIEngine()
        engine.load_model(model_size="whisper-1")
        init_time = time.time() - start_init
        print(f"✓ Engine initialized in {init_time:.2f}s")

        print("Transcribing audio (uploading to OpenAI)...")
        start_transcribe = time.time()
        result = engine.transcribe(audio, language="en")
        transcribe_time = time.time() - start_transcribe
        print(f"✓ Transcription complete in {transcribe_time:.2f}s")

        total_time = init_time + transcribe_time

        print("\nRESULTS:")
        print(f"  Text: {result.text}")
        if result.segments:
            print(f"  Confidence: {result.segments[0].confidence:.2%}")
        print(f"\nTIMING:")
        print(f"  API init:    {init_time:.2f}s (one-time)")
        print(f"  Transcribe:  {transcribe_time:.2f}s")
        print(f"  TOTAL:       {total_time:.2f}s")

        return {
            'name': 'OpenAI API',
            'text': result.text,
            'init_time': init_time,
            'transcribe_time': transcribe_time,
            'total_time': total_time,
        }

    except Exception as e:
        print(f"✗ Error: {e}")
        # Check for quota error
        if "insufficient_quota" in str(e):
            print("  (OpenAI account quota exceeded)")
        import traceback
        traceback.print_exc()
        return None

def main():
    print("=" * 60)
    print("WISPR DRAGON ENGINE BENCHMARK")
    print("=" * 60)

    # Capture audio once
    audio = capture_audio(duration_seconds=5)
    if audio is None:
        return 1

    results = []

    # Benchmark local
    local_result = benchmark_local_whisper(audio)
    if local_result:
        results.append(local_result)

    # Benchmark OpenAI (if key is set)
    if os.getenv('OPENAI_API_KEY'):
        openai_result = benchmark_openai_api(audio)
        if openai_result:
            results.append(openai_result)
    else:
        print("\n" + "=" * 60)
        print("OPENAI API (Cloud Whisper)")
        print("=" * 60)
        print("✗ OPENAI_API_KEY not set - skipping")

    # Summary
    if results:
        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)

        for result in results:
            print(f"\n{result['name']}:")
            if 'load_time' in result:
                print(f"  Model load:  {result['load_time']:.2f}s")
            if 'init_time' in result:
                print(f"  API init:    {result['init_time']:.2f}s")
            print(f"  Transcribe:  {result['transcribe_time']:.2f}s")
            print(f"  TOTAL:       {result['total_time']:.2f}s")

        if len(results) == 2:
            print("\n" + "=" * 60)
            faster = min(results, key=lambda x: x['transcribe_time'])
            slower = max(results, key=lambda x: x['transcribe_time'])
            speedup = slower['transcribe_time'] / faster['transcribe_time']

            print(f"WINNER: {faster['name']} is {speedup:.1f}x faster")
            print("=" * 60)

        return 0
    else:
        print("\nNo results to compare")
        return 1

if __name__ == "__main__":
    sys.exit(main())
