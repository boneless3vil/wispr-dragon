#!/usr/bin/env python3
"""Benchmark engines with a pre-recorded audio sample."""

import os
import sys
import time
import numpy as np

# Create a synthetic speech-like sample (1000 Hz sine wave + noise = pseudo-speech)
def create_sample_audio():
    """Create synthetic audio that looks like speech."""
    sample_rate = 16000
    duration = 5  # seconds

    t = np.linspace(0, duration, int(sample_rate * duration))

    # Synthetic "speech" - combination of frequencies
    audio = np.zeros_like(t)
    # Fundamental + some overtones (mimics speech formants)
    audio += 0.3 * np.sin(2 * np.pi * 150 * t)  # Fundamental
    audio += 0.2 * np.sin(2 * np.pi * 300 * t)  # 1st formant
    audio += 0.15 * np.sin(2 * np.pi * 600 * t)  # 2nd formant
    # Add some noise
    audio += 0.1 * np.random.randn(len(t))
    # Normalize
    audio = audio / np.max(np.abs(audio)) * 0.8

    return audio.astype(np.float32)

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
        print(f"  Text: {result.text if result.text else '(synthetic audio - no speech detected)'}")
        print(f"\nTIMING:")
        print(f"  Model load:  {load_time:.3f}s (one-time cost)")
        print(f"  Transcribe:  {transcribe_time:.3f}s")
        print(f"  TOTAL:       {total_time:.3f}s")

        return {
            'name': 'Local Whisper (Faster-Whisper)',
            'transcribe_time': transcribe_time,
            'load_time': load_time,
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
        print("✗ OPENAI_API_KEY not set")
        print("\nTo test OpenAI, set your API key:")
        print("  export OPENAI_API_KEY='sk-your-key-here'")
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
        print(f"\nTIMING:")
        print(f"  API init:    {init_time:.3f}s (one-time cost)")
        print(f"  Transcribe:  {transcribe_time:.3f}s")
        print(f"  TOTAL:       {total_time:.3f}s")

        return {
            'name': 'OpenAI API (Cloud Whisper)',
            'transcribe_time': transcribe_time,
            'init_time': init_time,
            'total_time': total_time,
        }

    except Exception as e:
        error_msg = str(e)
        print(f"✗ Error: {error_msg}")
        if "insufficient_quota" in error_msg:
            print("  Your OpenAI account has hit its usage quota")
            print("  Check: https://platform.openai.com/account/billing/overview")
        return None

def main():
    print("=" * 60)
    print("WISPR DRAGON ENGINE BENCHMARK")
    print("(Using synthetic audio sample)")
    print("=" * 60)

    # Create sample audio
    print("\nGenerating synthetic audio sample (5 seconds)...")
    audio = create_sample_audio()
    peak = np.max(np.abs(audio))
    print(f"✓ Audio generated: {audio.shape[0]} samples, peak={peak:.3f}")

    results = []

    # Benchmark local
    local_result = benchmark_local_whisper(audio)
    if local_result:
        results.append(local_result)

    # Benchmark OpenAI
    openai_result = benchmark_openai_api(audio)
    if openai_result:
        results.append(openai_result)

    # Summary
    if results:
        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)

        for result in results:
            print(f"\n{result['name']}:")
            if 'load_time' in result:
                print(f"  Model load:   {result['load_time']:.3f}s (one-time)")
            if 'init_time' in result:
                print(f"  API init:     {result['init_time']:.3f}s (one-time)")
            print(f"  Transcribe:   {result['transcribe_time']:.3f}s")
            print(f"  Total (first): {result['total_time']:.3f}s")

        if len(results) == 2:
            print("\n" + "=" * 60)
            print("ANALYSIS")
            print("=" * 60)

            local = next((r for r in results if 'Local' in r['name']), None)
            openai = next((r for r in results if 'OpenAI' in r['name']), None)

            if local and openai:
                speedup = openai['transcribe_time'] / local['transcribe_time']
                print(f"\n🚀 Local Whisper is {speedup:.0f}x FASTER than OpenAI API")
                print(f"   Local:  {local['transcribe_time']:.3f}s per transcription")
                print(f"   OpenAI: {openai['transcribe_time']:.3f}s per transcription")
                print(f"\n💰 Cost comparison (for 1 hour of audio):")
                print(f"   Local:  $0 (free)")
                print(f"   OpenAI: ${1 * 0.02:.2f} (at $0.02/min)")
                print(f"\n✅ RECOMMENDATION: Use Local Whisper for speed & cost")

        return 0
    else:
        print("\nCouldn't run any benchmarks")
        return 1

if __name__ == "__main__":
    sys.exit(main())
