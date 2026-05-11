# OpenAI API Whisper Setup Guide

This guide covers setting up Wispr Dragon to use the OpenAI API for speech recognition, including the new GPT 5.5 model.

## Why Use OpenAI API?

- **Latest models** - Access to the newest OpenAI Whisper models (including GPT 5.5)
- **Cloud-based** - No local GPU required
- **Accurate** - Cloud models benefit from continuous improvements
- **Flexible** - Works on any hardware (Raspberry Pi, old laptops, etc.)

**Trade-off:** API costs ~$0.02-0.03 per minute of audio

## Step 1: Get API Key

1. Go to [https://platform.openai.com/account/api-keys](https://platform.openai.com/account/api-keys)
2. Sign in or create a free account
3. Click "Create new secret key"
4. Copy the key (starts with `sk-`)
5. Store it securely - never commit to git!

## Step 2: Install Dependencies

```bash
# Install OpenAI SDK and audio conversion library
pip install openai pydub

# Or from project directory:
pip install -e ".[openai-api]"
```

## Step 3: Set Environment Variable

### Linux/WSL:
```bash
export OPENAI_API_KEY="sk-your-key-here"

# Make it permanent (add to ~/.bashrc or ~/.zshrc):
echo 'export OPENAI_API_KEY="sk-your-key-here"' >> ~/.bashrc
source ~/.bashrc
```

### Windows PowerShell:
```powershell
$env:OPENAI_API_KEY = "sk-your-key-here"

# Make it permanent:
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-your-key-here", [EnvironmentVariableTarget]::User)
```

## Step 4: Configure Wispr Dragon

Edit or create `~/.wispr-dragon/config.yaml`:

```yaml
engine:
  backend: openai-api          # Use the API engine
  model_size: whisper-1        # Standard model
  language: en
  beam_size: 5
  initial_prompt: "Technical conversation about software engineering."
  hotwords: "Python, JavaScript, TypeScript, React, Docker, Kubernetes"

audio:
  sample_rate: 16000
  vad_threshold: 0.5
  silence_duration_ms: 500
```

## Step 5: Run Wispr Dragon

```bash
# Verify API key is set
echo $OPENAI_API_KEY

# Start the application
wispr-dragon --verbose

# You should see:
# INFO [wispr_dragon.main] Wispr-Dragon starting...
# INFO [wispr_dragon.main] Using openai-api engine
# INFO [wispr_dragon.main] Model loaded successfully
```

## Testing

### Quick Test

```bash
python scripts/test_audio.py
python scripts/test_integration.py
```

### Manual Test

```python
python3 << 'EOF'
import os
from wispr_dragon.engine.openai_api_engine import OpenAIAPIEngine
import numpy as np

# Check API key
if not os.getenv("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not set")
    exit(1)

# Initialize engine
engine = OpenAIAPIEngine()
print(f"API available: {engine.is_available()}")

engine.load_model(model_size="whisper-1")

# Create test audio (silence)
audio = np.zeros(16000, dtype=np.float32)
result = engine.transcribe(audio)
print(f"Result: '{result.text}'")
print(f"Success!")
EOF
```

## Available Models

Currently available via OpenAI API:

| Model | Name | Speed | Accuracy | Cost |
|-------|------|-------|----------|------|
| Whisper-1 | Standard | Fast | Good | $0.02/min |
| GPT 5.5* | New | Medium | Excellent | $0.03/min |

*Available when released

## Cost Estimation

Typical usage costs:

| Scenario | Hours/Month | Cost/Month |
|----------|-------------|-----------|
| Light (1 hr/day) | 30 | ~$36 |
| Medium (2 hrs/day) | 60 | ~$72 |
| Heavy (4 hrs/day) | 120 | ~$144 |

Monitor usage at: https://platform.openai.com/account/billing/overview

## Troubleshooting

### "OPENAI_API_KEY environment variable not set"

```bash
# Check if variable is set
echo $OPENAI_API_KEY

# If empty, set it
export OPENAI_API_KEY="sk-..."

# Verify it's set
echo $OPENAI_API_KEY
```

### "API error: 401 Invalid authentication"

Your API key is invalid or expired:
1. Go to [https://platform.openai.com/account/api-keys](https://platform.openai.com/account/api-keys)
2. Delete old keys
3. Create a new one
4. Update `OPENAI_API_KEY`

### "API error: 429 Rate limit exceeded"

You're hitting rate limits:
1. Wait 30 seconds
2. Upgrade to paid account for higher limits
3. Check usage at https://platform.openai.com/account/billing/usage

### Audio conversion fails (pydub error)

Install ffmpeg:

```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Windows (with conda)
conda install -c conda-forge ffmpeg
```

### "No transcription engine available"

Make sure dependencies are installed:

```bash
pip install -e ".[openai-api]"
```

## Advanced Configuration

### Using GPT 5.5 (when available)

```yaml
engine:
  backend: openai-api
  model_size: gpt-5.5  # Update when released
```

### Temperature Control

Lower temperature = more conservative (default 0.0):

```python
# In openai_api_engine.py, line ~76:
transcript = self._client.audio.transcriptions.create(
    temperature=0.0,  # 0.0-1.0
    ...
)
```

### Custom Initial Prompts

Help the API understand context:

```yaml
engine:
  initial_prompt: "This is a medical consultation about heart surgery. Technical terms are expected."
```

### Hotwords

Bias recognition toward important terms:

```yaml
engine:
  hotwords: "Kubernetes, Docker, microservices, API gateway, load balancer"
```

## Fallback Strategy

If OpenAI API fails, you can fall back to local models:

```yaml
engine:
  backend: auto  # Tries faster-whisper, then local whisper, then API
```

When OPENAI_API_KEY isn't set, it automatically uses local models if available.

## Security Notes

- Never commit API keys to git
- Use `.env` file for local development:
  ```bash
  # .env (add to .gitignore)
  OPENAI_API_KEY=sk-...
  
  # Load before running:
  export $(cat .env | xargs)
  wispr-dragon
  ```
- Rotate keys periodically
- Monitor usage for unexpected charges

## More Resources

- [OpenAI Whisper API Documentation](https://platform.openai.com/docs/api-reference/audio)
- [OpenAI Pricing](https://openai.com/pricing/whisper-api)
- [API Status](https://status.openai.com/)

## Support

For issues:
1. Check logs with `wispr-dragon --verbose`
2. Run `python scripts/test_integration.py`
3. Open an issue on GitHub
