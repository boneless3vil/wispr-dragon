# Wispr Dragon Benchmark Scripts

Utilities for testing and benchmarking audio capture, device detection, and transcription engines.

## Scripts

### `test_devices.py`
Lists all available audio input devices and their capabilities.

```bash
python test_devices.py
```

### `test_openai_transcription.py`
Tests OpenAI Whisper API integration with live microphone input.

**Requirements**: `OPENAI_API_KEY` environment variable must be set

```bash
export OPENAI_API_KEY='sk-your-key-here'
python test_openai_transcription.py
```

Captures 5 seconds of audio and transcribes via OpenAI API.

### `benchmark_engines.py`
Benchmarks local Faster-Whisper vs OpenAI API with live microphone audio.

**Requirements**: `OPENAI_API_KEY` environment variable (optional for local-only comparison)

```bash
python benchmark_engines.py
```

Captures 5 seconds of audio and measures:
- Model load time
- Transcription time
- Total latency
- Transcription text for both engines

### `benchmark_with_sample.py`
Benchmarks engines with synthetic audio (no microphone required).

```bash
python benchmark_with_sample.py
```

Generates synthetic speech-like audio and compares:
- Speed (transcription latency)
- Cost comparison ($0 for local vs $0.02/min for OpenAI)
- Recommendations

## Running from Project Root

```bash
cd ~/wispr_dragon
source venv/bin/activate

# List audio devices
python scripts/benchmark/test_devices.py

# Test OpenAI API
python scripts/benchmark/test_openai_transcription.py

# Benchmark both engines with live audio
python scripts/benchmark/benchmark_engines.py

# Benchmark with synthetic audio (no mic needed)
python scripts/benchmark/benchmark_with_sample.py
```

## Notes

- Live audio benchmarks require a working microphone
- Synthetic benchmark is useful for testing without audio hardware
- All benchmarks report timing metrics for regression testing
- OpenAI API benchmarks require valid API key and account with available quota
