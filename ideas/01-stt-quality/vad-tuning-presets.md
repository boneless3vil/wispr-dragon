# VAD tuning presets

## Problem

Defaults in `AudioConfig`: `vad_threshold=0.5`, `silence_duration_ms=500`, `min_speech_duration_ms=250`. These are reasonable but wrong for everyone:

- **Fast dictators**: 500 ms of silence between sentences is too long — adds perceived latency.
- **Thinkers**: 500 ms cuts segments mid-thought; the engine sees half a sentence and emits weird punctuation.
- **Noisy environments**: threshold 0.5 picks up keyboard clicks and HVAC as speech.

## Solution

Named presets in `config.py`:

```python
VAD_PRESETS = {
    "fast":     {"threshold": 0.6, "silence_ms": 250, "min_speech_ms": 200},
    "default":  {"threshold": 0.5, "silence_ms": 500, "min_speech_ms": 250},
    "thinker":  {"threshold": 0.5, "silence_ms": 900, "min_speech_ms": 250},
    "noisy":    {"threshold": 0.75, "silence_ms": 500, "min_speech_ms": 400},
}
```

Settings UI exposes a 4-button selector with one-line descriptions. Power users keep the granular knobs in the YAML.

## Effort

Trivial — a few hours including the UI.
