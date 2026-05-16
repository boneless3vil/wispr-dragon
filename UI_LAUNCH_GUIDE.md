# Wispr Dragon — Floating Dictation Box UI 🎤

## Overview

The Wispr Dragon floating dictation box is a minimal, always-on-top window for voice-to-text input. It mimics Dragon 16.1's iconic dictation interface: you speak, it transcribes in real-time, you hit **Post** to inject the text into your active application.

## Requirements

**PyQt6 must be installed:**
```bash
pip install PyQt6
```

Plus standard Wispr Dragon dependencies:
- `sounddevice` (audio capture)
- `numpy` (audio processing)
- Your transcription engine (faster-whisper, openai-whisper, or openai-api)

## Launching the UI

### From Command Line

**Launch the floating dictation box:**
```bash
python -m wispr_dragon --ui
```

**With verbose logging:**
```bash
python -m wispr_dragon --ui --verbose
```

**Override model/device:**
```bash
python -m wispr_dragon --ui --model base.en --device cpu
```

### What You'll See

A small floating window (~500×250px) appears with:

```
┌──────────────────────────────────┐
│ 🎤 Dictation Active              │
│                                  │
│ [Live transcription appears here] │
│                                  │
│ [Post]  [Clear]  [Cancel]        │
└──────────────────────────────────┘
```

**Status bar** at the bottom shows recording state and character count.

## How It Works

1. **Click the window** or just start speaking
2. **Live transcription** appears as you speak (shown in black)
3. **Final segments** accumulate as the engine processes them
4. **Hit Post [↵]** to inject the final text into your active window
5. **Hit Clear [Ctrl+L]** to discard and start over
6. **Hit Cancel [Esc]** to close without posting

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `↵ Enter` | Post text to active window |
| `Esc` | Cancel (close without posting) |
| `Ctrl+L` | Clear current text |

## Architecture

The UI runs three components in parallel:

### DictationBox (PyQt6 UI)
- Minimal floating window
- Displays transcription
- Handles button clicks + keyboard events
- Status bar updates

### AudioWorker (Thread)
- Captures audio from your microphone
- Runs in background thread
- Non-blocking; calls callback with audio chunks

### TranscriptionWorker (Thread)
- Processes audio chunks via the engine
- Maintains a buffer (capped at 30 seconds)
- Emits live + final transcription events
- Post-processes text (corrections, capitalization)

### UIController (Orchestrator)
- Ties the three components together
- Manages threads and signal/slot connections
- Injects text into active window on Post
- Handles errors gracefully

## Configuration

All settings come from `~/.wispr_dragon/config.yaml`:

```yaml
audio:
  sample_rate: 16000
  vad_threshold: 0.5
  silence_duration_ms: 500
  min_speech_duration_ms: 250

engine:
  backend: auto          # auto, faster-whisper, openai-whisper, openai-api
  model_size: base.en
  device: auto           # auto, cuda, cpu
  compute_type: auto     # auto, float16, int8, float32
```

Override via CLI:
```bash
python -m wispr_dragon --ui --device cuda --model small.en
```

## Next Steps

The dictation box is ready for:
- **System tray icon** — start/stop recording from desktop
- **Settings dialog** — adjust config via GUI
- **Macro editor** — create voice commands visually
- **Real-time transcription overlay** — fullscreen dictation mode

For now, the command line works great! 🎉

---

**Questions?** Check the main README.md or test suite (tests/test_ui_components.py).
