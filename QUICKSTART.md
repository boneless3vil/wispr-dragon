# Wispr Dragon Quick Start

## 5-Minute Setup

### 1. Clone and Install
```bash
cd wispr-dragon
conda env create -f environment.yml
conda activate wispr-dragon
pip install -e .
```

### 2. Test Audio
```bash
python scripts/test_audio.py
```

### 3. Run
```bash
wispr-dragon
```

---

## Using OpenAI API (GPT 5.5 Support)

### 1. Get API Key
Visit: https://platform.openai.com/account/api-keys

### 2. Set Environment
```bash
export OPENAI_API_KEY="sk-..."
```

### 3. Configure
Create `~/.wispr-dragon/config.yaml`:
```yaml
engine:
  backend: openai-api
  model_size: whisper-1
```

### 4. Run
```bash
wispr-dragon
```

---

## Comparison: Local vs Cloud

| Feature | Faster-Whisper | OpenAI API |
|---------|---|---|
| Cost | Free | $0.02/min |
| GPU Required | Yes | No |
| Latest Models | No | Yes (GPT 5.5) |
| Privacy | Local | Cloud |
| Speed | Medium | Slow (network) |
| Accuracy | Good | Excellent |
| Setup | Complex | Simple |

---

## Common Commands

```bash
# Default (auto-detects engine)
wispr-dragon

# Verbose logging
wispr-dragon --verbose

# Override model
wispr-dragon --model large-v3

# Specific engine
wispr-dragon --backend openai-api

# Custom config
wispr-dragon --config /path/to/config.yaml

# Disable VAD
wispr-dragon --no-vad

# Show help
wispr-dragon --help
```

---

## Troubleshooting

### No Audio
```bash
# Test audio system
python scripts/test_audio.py

# Check microphone
parecord --format=s16le --rate=16000 --channels=1 test.wav
```

### API Key Error
```bash
# Verify key is set
echo $OPENAI_API_KEY

# Get new key from https://platform.openai.com/account/api-keys
```

### Model Download Issues
```bash
# Pre-download models
python -c "from faster_whisper import WhisperModel; WhisperModel('medium')"
```

---

## Test Suite

```bash
# Audio capture test
python scripts/test_audio.py

# Integration tests
python scripts/test_integration.py

# Unit tests
pytest tests/
```

---

## File Structure

```
wispr-dragon/
├── wispr_dragon/
│   ├── engine/              # Transcription engines
│   │   ├── openai_api_engine.py       # NEW: Cloud API
│   │   ├── openai_whisper_engine.py   # Local PyTorch
│   │   └── faster_whisper_engine.py   # Optimized local
│   ├── audio/              # Audio capture & VAD
│   ├── correction/         # Text processing
│   ├── modes/              # Command/Dictation
│   ├── output/             # Text injection
│   └── main.py             # Entry point
├── scripts/
│   ├── test_audio.py       # Audio testing
│   ├── test_integration.py # Full integration
│   └── test_transcription.py
├── README.md               # Full documentation
├── SETUP_OPENAI_API.md     # API setup guide
└── QUICKSTART.md           # This file
```

---

## Next Steps

1. **[Test audio capture](scripts/test_audio.py)**
   ```bash
   python scripts/test_audio.py
   ```

2. **[Choose engine](#comparison-local-vs-cloud)**
   - Local: Fast, free, needs GPU
   - Cloud: Accurate, costs money, simple setup

3. **[Configure](#using-openai-api-gpt-55-support)** `~/.wispr-dragon/config.yaml`

4. **[Run](#run)** and start using!

---

## Key Files Created/Modified

### New Files
- `wispr_dragon/engine/openai_api_engine.py` - OpenAI API engine with GPT 5.5 support
- `scripts/test_integration.py` - Integration test suite
- `README.md` - Full documentation
- `SETUP_OPENAI_API.md` - API setup guide

### Modified Files
- `wispr_dragon/main.py` - Added OpenAI API engine support
- `wispr_dragon/config.py` - Added openai-api backend option
- `wispr_dragon/audio/capture.py` - Improved initialization
- `scripts/test_audio.py` - Complete rewrite with better testing
- `pyproject.toml` - Added openai-api optional dependencies

---

## API Models

**Currently Available:**
- `whisper-1` - Standard OpenAI Whisper API model

**Coming Soon:**
- `gpt-5.5` - Next-generation model with improved accuracy (update config when available)

---

## Tips & Tricks

### Improve Recognition
```yaml
engine:
  initial_prompt: "Context about what you're speaking about..."
  hotwords: "Important terms, separated, by commas"
```

### Reduce Costs
```yaml
engine:
  beam_size: 1  # Faster, less accurate (default 5)
```

### Silence Detection
```yaml
audio:
  vad_threshold: 0.7        # More aggressive, faster
  silence_duration_ms: 300  # Shorter gaps trigger end-of-speech
```

---

## Support

- **Documentation**: See README.md
- **Setup Help**: See SETUP_OPENAI_API.md
- **Issues**: Open a GitHub issue
- **Questions**: Check the docs first!

---

## What's New

✨ **GPT 5.5 Support** - Ready for OpenAI's latest model
✨ **OpenAI API Engine** - Cloud transcription without local GPU
✨ **Better Testing** - Comprehensive test suite
✨ **Improved Audio** - Robust audio initialization
✨ **Full Documentation** - Setup guides and API docs
