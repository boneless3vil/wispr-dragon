# Wispr Dragon

A powerful speech recognition application for Linux/WSL2 with support for multiple transcription backends.

> 📖 **New here? See the [User Manual](docs/USER_MANUAL.md)** — how to run it,
> the hotkey and microphone, dictating with spoken punctuation, voice commands
> and modes, correction and vocabulary, macros, every keyboard shortcut, and a
> full CLI + configuration reference.

## Features

- **Multiple transcription engines:**
  - OpenAI API Whisper (cloud-based, includes GPT 5.5 support)
  - Local Whisper (PyTorch-based)
  - Faster-Whisper (optimized local inference)
- **Voice Activity Detection (VAD)** - Silero VAD for precise speech detection
- **Audio capture** from microphone with PulseAudio support
- **Fallback network audio** for Windows host audio streaming
- **Command mode** - Execute voice commands
- **Dictation mode** - Transcribe continuous speech
- **Post-processing** - Custom dictionaries and hotwords
- **Text injection** - Automatically type transcribed text

## Installation

### Prerequisites

- **Python 3.11+**
- **Microphone** for audio input (physical, USB, or network)
- **CUDA/ROCm** (optional, for GPU acceleration with faster-whisper)

### Option 1: PyPI Install (Recommended for Users)

```bash
# CLI only (minimal dependencies)
pip install wispr_dragon

# With GUI (floating dictation box)
pip install wispr_dragon[gui]

# With optional transcription engines
pip install wispr_dragon[gui,openai-api,whisper-fallback]

# Then run
wispr_dragon --help
wispr_dragon --ui  # Launch floating dictation box
```

### Option 2: Development Install (For Contributors)

```bash
# Clone the repository
git clone https://github.com/yourusername/wispr_dragon.git
cd wispr_dragon

# Create environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode with all extras
pip install -e ".[gui,dev,openai-api,whisper-fallback]"

# Run tests
pytest tests/ -v
```

### Audio Setup (WSL2)

Ensure PulseAudio is working:

```bash
# Test audio capture
python scripts/test_audio.py

# If PulseAudio issues persist, use network audio mode
# (Configure Windows-side audio capture server)
```

### GPU Setup (Optional)

For faster transcription, enable GPU acceleration:

#### NVIDIA CUDA

```bash
# Install CUDA-enabled PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# For faster-whisper
pip install faster-whisper[cuda]
```

#### AMD ROCm

```bash
# Install ROCm-enabled PyTorch (Ubuntu)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.0

# For faster-whisper, use community ROCm builds
pip install faster-whisper  # May require manual ROCm CTranslate2
```

Set device in config:

```yaml
engine:
  device: cuda  # or rocm, auto, cpu
  compute_type: float16  # Use float16 for GPU acceleration
```

## Usage

### Quick Start

```bash
# Run with auto-detected engine
python -m wispr_dragon

# Or use the main entry point
wispr_dragon
```

### Using OpenAI API Engine (GPT 5.5)

#### Setup

1. Get an OpenAI API key from [https://platform.openai.com/account/api-keys](https://platform.openai.com/account/api-keys)

2. Set environment variable:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

#### Configuration

Edit `~/.wispr_dragon/config.yaml`:

```yaml
engine:
  backend: openai-api
  model_size: whisper-1  # or gpt-5.5 when available
  language: en
  initial_prompt: "This is a technical conversation about software development."
  hotwords: "Python, JavaScript, database"
```

#### Running

```bash
# Auto-selects OpenAI API if OPENAI_API_KEY is set
wispr-dragon

# Or explicitly select it
wispr-dragon --device auto
```

### Using Local Whisper Engine

#### Install Dependencies

For faster-whisper (recommended):
```bash
pip install faster-whisper
```

For original PyTorch Whisper:
```bash
pip install openai-whisper torch
```

#### Configuration

```yaml
engine:
  backend: faster-whisper
  model_size: medium.en
  device: auto
  compute_type: float16  # or int8, float32
```

### Command Line Options

```bash
wispr_dragon --help

# Examples:
wispr_dragon --verbose                    # Debug output
wispr_dragon --model large-v3             # Override model size
wispr_dragon --device cuda                # Force GPU
wispr_dragon --no-vad                     # Disable voice activity detection
wispr_dragon --config /path/to/config.yaml
```

## Testing

### Audio Tests

```bash
# Test microphone and audio capture
python scripts/test_audio.py

# This verifies:
# - sounddevice availability
# - Audio capture initialization
# - Voice Activity Detection (VAD)
```

### Transcription Tests

```bash
# Test transcription engines
python scripts/test_transcription.py

# Integration tests
python scripts/test_integration.py
```

## Configuration

### Default Config Location
`~/.wispr_dragon/config.yaml`

### Audio Configuration

```yaml
audio:
  sample_rate: 16000
  channels: 1
  vad_threshold: 0.5              # 0.0-1.0, higher = more aggressive
  silence_duration_ms: 500        # Duration to trigger end-of-speech
  min_speech_duration_ms: 250     # Minimum speech segment length
  source: pulseaudio              # or "network"
  network_host: 0.0.0.0
  network_port: 9876
```

### Engine Configuration

```yaml
engine:
  backend: auto                   # auto, faster-whisper, openai-whisper, openai-api
  model_size: medium.en           # Model variant
  device: auto                    # auto, cuda, cpu
  compute_type: auto              # auto, float16, int8, float32
  language: en
  beam_size: 5                    # Larger = more accurate but slower
  initial_prompt: ""              # Bias towards certain phrases
  hotwords: ""                    # Important words to recognize
```

### Correction Configuration

```yaml
correction:
  auto_apply_threshold: 3         # Auto-apply corrections above this confidence
  fuzzy_match_score: 85           # 0-100, fuzzy match tolerance
  max_hotwords: 100
  save_audio_segments: false
```

## Modes

### Command Mode (Default)

Execute voice commands defined in `~/.wispr_dragon/commands.yaml`:

```yaml
commands:
  - phrase: "open [app]"
    action: "shell"
    template: "xdg-open"
  
  - phrase: "switch to [window]"
    action: "keystroke"
    keys: "alt+Tab"
```

### Dictation Mode

Continuous text transcription. Toggle with configured shortcut (default: `Ctrl+Shift+C`).

## Troubleshooting

### No Audio Input

**WSL2:**
```bash
# Check PulseAudio
parecord --format=s16le --rate=16000 --channels=1 test.wav
paplay test.wav

# Check DISPLAY variable
echo $DISPLAY  # Should show :0 or similar
```

**Network Audio (Windows host):**
```bash
# Use network audio mode instead of PulseAudio
# Configure config.yaml:
audio:
  source: network
  network_host: 0.0.0.0
  network_port: 9876
```

### Model Download Issues

```bash
# Pre-download models
python -c "from faster_whisper import WhisperModel; WhisperModel('medium')"

# Or for OpenAI Whisper:
python -c "import whisper; whisper.load_model('medium')"
```

### OpenAI API Errors

```bash
# Verify API key
echo $OPENAI_API_KEY

# Check API quota at https://platform.openai.com/account/billing/overview

# Enable debug logging
wispr-dragon --verbose
```

## Architecture

### Components

- **Audio Capture** (`wispr_dragon/audio/capture.py`)
  - PulseAudio stream or network socket
  - 16-bit PCM, 16kHz, mono

- **Voice Activity Detection** (`wispr_dragon/audio/vad.py`)
  - Silero VAD model
  - Returns speech segments

- **Transcription Engines** (`wispr_dragon/engine/`)
  - `base.py` - Abstract interface
  - `faster_whisper_engine.py` - Local optimized
  - `openai_whisper_engine.py` - Local PyTorch
  - `openai_api_engine.py` - Cloud API (NEW: GPT 5.5 support)

- **Text Processing** (`wispr_dragon/correction/`)
  - User dictionary
  - Hotword manager
  - Post-processor

- **Output** (`wispr_dragon/output/`)
  - Text injection via xdotool

- **Modes** (`wispr_dragon/modes/`)
  - Command mode
  - Dictation mode

## API Usage (Development)

```python
from wispr_dragon.config import Config
from wispr_dragon.engine.openai_api_engine import OpenAIAPIEngine
import numpy as np

# Initialize engine
engine = OpenAIAPIEngine()
engine.load_model(model_size="whisper-1")

# Transcribe audio
audio = np.random.randn(16000 * 5)  # 5 seconds
result = engine.transcribe(audio, language="en")

print(result.text)
print(f"Confidence: {result.segments[0].confidence}")
```

## Contributing

Contributions welcome! Please ensure:
- Code follows PEP 8
- Tests pass: `pytest tests/`
- Audio tests pass: `python scripts/test_audio.py`

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Support

For issues and feature requests, please open a GitHub issue.

For questions about the OpenAI API, see:
- [OpenAI Whisper API Docs](https://platform.openai.com/docs/api-reference/audio)
- [Pricing](https://openai.com/pricing/whisper-api)
