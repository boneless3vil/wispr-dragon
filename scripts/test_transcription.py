#!/usr/bin/env python3
"""Test transcription engine with a sample audio file or microphone."""

import argparse
import sys
import time

import numpy as np


def test_with_file(audio_path: str, engine_name: str, model_size: str):
    """Test transcription with a WAV file."""
    print(f"Loading audio from: {audio_path}")

    try:
        import soundfile as sf
        audio, sr = sf.read(audio_path, dtype="float32")
    except ImportError:
        import wave
        with wave.open(audio_path, "rb") as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    # Resample to 16kHz if needed
    if sr != 16000:
        print(f"  Resampling from {sr}Hz to 16000Hz...")
        ratio = 16000 / sr
        new_len = int(len(audio) * ratio)
        audio = np.interp(
            np.linspace(0, len(audio), new_len),
            np.arange(len(audio)),
            audio,
        )

    print(f"  Audio duration: {len(audio) / 16000:.1f}s")

    # Create engine
    engine = _create_engine(engine_name)
    print(f"  Engine: {engine.name}")
    print(f"  Loading model: {model_size}...")
    start = time.time()
    engine.load_model(model_size)
    load_time = time.time() - start
    print(f"  Model loaded in {load_time:.1f}s")

    # Transcribe
    print("  Transcribing...")
    start = time.time()
    result = engine.transcribe(audio)
    transcribe_time = time.time() - start

    print(f"\n  Result: {result.text}")
    print(f"  Time: {transcribe_time:.2f}s")
    print(f"  RTF: {transcribe_time / (len(audio) / 16000):.2f}x")
    print(f"  Segments: {len(result.segments)}")
    for seg in result.segments:
        print(f"    [{seg.start:.1f}-{seg.end:.1f}] {seg.text}")


def test_with_microphone(engine_name: str, model_size: str, duration: int = 5):
    """Test transcription with live microphone input."""
    import sounddevice as sd

    print(f"Recording {duration}s from microphone...")
    audio = sd.rec(
        int(duration * 16000),
        samplerate=16000,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    audio = audio.flatten()
    print(f"  Recorded {len(audio) / 16000:.1f}s of audio")

    engine = _create_engine(engine_name)
    print(f"  Engine: {engine.name}")
    print(f"  Loading model: {model_size}...")
    engine.load_model(model_size)

    print("  Transcribing...")
    start = time.time()
    result = engine.transcribe(audio)
    elapsed = time.time() - start

    print(f"\n  Result: {result.text}")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  RTF: {elapsed / (len(audio) / 16000):.2f}x")


def _create_engine(name: str):
    from wispr_dragon.config import Config
    from wispr_dragon.engine import create_engine

    config = Config()
    if name != "auto":
        config.engine.backend = name
    return create_engine(config)


def main():
    parser = argparse.ArgumentParser(description="Test Wispr-Dragon transcription")
    parser.add_argument("--file", type=str, help="Path to a WAV file to transcribe")
    parser.add_argument("--mic", action="store_true", help="Record from microphone")
    parser.add_argument("--duration", type=int, default=5, help="Mic recording duration (seconds)")
    parser.add_argument("--engine", type=str, default="auto",
                        choices=["auto", "faster-whisper", "openai-whisper"])
    parser.add_argument("--model", type=str, default="small.en",
                        help="Model size (tiny.en, base.en, small.en, medium.en, large-v3)")
    args = parser.parse_args()

    print("=" * 50)
    print("Wispr-Dragon Transcription Test")
    print("=" * 50)

    if args.file:
        test_with_file(args.file, args.engine, args.model)
    elif args.mic:
        test_with_microphone(args.engine, args.model, args.duration)
    else:
        print("Specify --file <path.wav> or --mic to test")
        sys.exit(1)


if __name__ == "__main__":
    main()
