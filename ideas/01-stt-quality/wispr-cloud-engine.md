# Wispr cloud engine

## Problem

CLAUDE.md says:

> **STT engines**: Wispr (cloud) and faster-whisper (local) as primary backends, with OpenAI API and openai-whisper as fallbacks.

But the code disagrees:

- `wispr_dragon/engine/` contains only `faster_whisper_engine.py`, `openai_api_engine.py`, `openai_whisper_engine.py`. No Wispr engine.
- `EngineConfig.backend` (`config.py:56-67`) validates against `{"auto", "faster-whisper", "openai-whisper", "openai-api"}` — "wispr" would raise `ValueError`.
- `pyproject.toml` has no `wispr` extra.

The "primary" backend doesn't exist. Either the vision needs to be updated or the engine needs to be built. Assuming the vision is the goal: build it.

## Solution

New file `wispr_dragon/engine/wispr_engine.py`:

```python
class WisprEngine(TranscriptionEngine):
    """Wispr cloud STT backend."""

    @property
    def name(self) -> str:
        return "wispr"

    def load_model(self, model_size, device="auto", compute_type="auto"):
        # Validate API key, open a long-lived HTTPS session, prefetch routing.
        ...

    def transcribe(self, audio, language="en", initial_prompt="",
                   hotwords="", beam_size=5) -> TranscriptionResult:
        # POST audio (wav/flac) to Wispr endpoint, parse response,
        # return TranscriptionResult populated with segments and words.
        ...

    def transcribe_partial(self, audio_so_far) -> str:
        # Wispr likely supports a streaming endpoint — use it.
        ...

    def is_available(self) -> bool:
        return bool(os.environ.get("WISPR_API_KEY"))
```

Wire-up:

1. Add `"wispr"` to `EngineConfig.backend` valid set in `config.py`.
2. Register in `engine/__init__.py` (`create_engine` factory).
3. Add `wispr` extra to `pyproject.toml` `[project.optional-dependencies]`.
4. Document the env var (`WISPR_API_KEY`) in README + `config.py` docstrings.
5. Update `gpu_advisor.py` so that when `backend=auto` and the API key is present, "wispr" wins on machines without a GPU.

## Auto-selection logic (the "auto" backend)

Currently `auto` doesn't have explicit precedence documented. With Wispr in the mix, the rule should be:

1. If `WISPR_API_KEY` set → wispr.
2. Else if GPU detected (`gpu_advisor.recommend()`) → faster-whisper.
3. Else if `OPENAI_API_KEY` set → openai-api.
4. Else → faster-whisper on CPU with small.en.
5. Last resort → openai-whisper (pure Python fallback).

This needs to be a single function (`select_engine(config) -> str`) with unit tests covering each rung.

## Affected files

- New `wispr_dragon/engine/wispr_engine.py`.
- `wispr_dragon/engine/__init__.py` — register, factory.
- `wispr_dragon/engine/base.py` — possibly add `transcribe_partial`.
- `wispr_dragon/config.py` — extend `EngineConfig.backend` valid set; add `WisprConfig` if endpoint URL / region are needed.
- `pyproject.toml` — `wispr` extra.
- `tests/test_engine_factory.py` — cover wispr-selection paths.
- `wispr_dragon/engine/gpu_advisor.py` — re-rank with wispr present.

## Effort

Medium-small once the Wispr API is decided. The interface is already abstract, so most of the work is HTTP + response parsing + error handling.

## Open questions

- **Which "Wispr"?** The name is overloaded — there's Wispr Flow (the dictation app) and there may be an underlying API the team is targeting. Worth pinning down before implementation: is this an internal API, a partner API, or a planned in-house service?
- **Pricing & rate limits**: shape the fallback chain ([engine-fallback-chain](engine-fallback-chain.md)) around the real limits.
- **Audio format**: cloud engines typically prefer 16 kHz mono PCM or flac. The pipeline already produces 16 kHz mono int16; encoding cost is trivial.
