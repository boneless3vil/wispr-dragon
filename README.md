# Wispr Dragon

Local, GPU-accelerated voice dictation with a Dragon NaturallySpeaking-style
feel: push-to-talk, spoken punctuation and capitalization, "correct that", and
a vocabulary that learns from your corrections.

> 📖 **The [User Manual](docs/USER_MANUAL.md) is the full reference** — the
> hotkey and microphone, spoken formatting, voice commands and modes, correction
> and vocabulary, macros, keyboard shortcuts, and every CLI flag and config key.

## How it fits together

Wispr Dragon is two programs:

- **Server** (Linux / WSL2) — receives audio over WebSocket, transcribes it with
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your GPU, and
  applies vocabulary + spoken formatting.
- **Client** (Windows today) — a tray app that captures your microphone while you
  hold the hotkey (Right-Ctrl by default), streams the audio, and pastes the
  returned text into whatever app has focus.

There is also a local all-in-one **desktop app** (`--ui`, Linux/WSLg only) that
additionally runs voice commands, modes and macros — see the manual, §1.

## Install

The package isn't on PyPI; install from a clone.

```bash
git clone https://github.com/boneless3vil/wispr-dragon.git
cd wispr-dragon
```

**Server** (Linux / WSL2, Python 3.11+, in a virtual environment):

```bash
python3 -m venv venv && source venv/bin/activate
# NVIDIA: the CUDA-12 torch build also supplies the cuBLAS/cuDNN CTranslate2 needs
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
pip install -e ".[server]"
```

**Windows client** (Python 3.11+, from PowerShell):

```powershell
pip install -e ".[client]"
```

Optional extras: `gui` (the local desktop app), `openai-api` (OpenAI's hosted
transcription), `whisper-fallback` (openai-whisper), `dev` (tests + ruff).
CPU-only and AMD/ROCm notes are in the comments of [`pyproject.toml`](pyproject.toml).

## Run

```bash
# 1. On the server — prints the API key, LAN address and a ready client config:
python -m wispr_dragon --server --print-key
python -m wispr_dragon --server
```

```powershell
# 2. On Windows — the first run opens a setup dialog for the server URL + key:
python -m wispr_dragon.client
```

Hold **Right-Ctrl**, speak, release: the sentence is transcribed as one
utterance and pasted at the cursor. Say "comma", "period", "new line", "cap",
"all caps"… for formatting, and "correct that" to fix the last phrase.

Configuration lives in `~/.wispr_dragon/config.yaml` (server / desktop app) and
`%LOCALAPPDATA%\WisprDragon\config.json` (Windows client) — both documented in
the manual, §10. A packaged Windows installer can be built from
[`packaging/`](packaging/README.md).

## Development

```bash
pip install -e ".[dev,server,client]"
pytest                 # headless; no GPU, mic or network needed
ruff check .
```

Project layout and conventions for contributors (and AI agents) are in
[CLAUDE.md](CLAUDE.md); planned work lives in [`ideas/`](ideas/INDEX.md).

## License

Apache 2.0 — see [LICENSE](LICENSE).
