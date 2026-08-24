# pyproject extras alignment

## Problem

CLAUDE.md lists extras: `gui`, `server`, `client`, `openai-api`, `whisper-fallback`, `dev`. The vision lists Wispr cloud as a primary engine — but there's no `wispr` extra. And future features (LLM post-processor, diarization, llama-cpp) will each want their own extra to keep installs lean.

## Fix

Update `pyproject.toml` `[project.optional-dependencies]` to add:

- `wispr` — Wispr cloud SDK / HTTP client (when [wispr-cloud-engine](../01-stt-quality/wispr-cloud-engine.md) lands).
- `llm-local` — `llama-cpp-python` (for [llm-post-processor](../04-differentiators/llm-post-processor.md)).
- `diarization` — `pyannote.audio` (for [diarization](../04-differentiators/diarization.md)).
- `macos` — `pyobjc-framework-Quartz`, `pyobjc-framework-ApplicationServices`.
- `linux` — currently nothing pip-installable required (ydotool/xdotool are system packages); keep as a no-op marker for symmetry.

And a meta-extra `all = ["wispr_dragon[gui,server,client,openai-api,whisper-fallback,wispr,llm-local]"]` so power users get one command.

## Effort

Trivial.
