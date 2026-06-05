# Copilot instructions for Wispr Dragon

Purpose: concise guidance for Copilot sessions to make effective edits and suggestions in this repo.

Build / Install
- User install (PyPI): `pip install wispr_dragon`
- Dev install (recommended): `pip install -e ".[gui,dev,openai-api,whisper-fallback]"`
- Packaging (optional): `python -m build` (requires `build` package)

Test
- Run full suite: `pytest tests/ -v` (pyproject.toml sets `-v --tb=short`)
- Run a single test file: `pytest tests/test_module.py -q`
- Run a single test function: `pytest tests/test_module.py::test_function`
- Run by expression: `pytest -k "substring"`
- Useful scripts: `python scripts/test_audio.py`, `python scripts/test_transcription.py`

Lint / Typecheck
- No enforced linter in CI. Preferred local tools:
  - `ruff .` (fast diagnostics)
  - `mypy --strict wispr_dragon` (type checks on changed modules)

Run / Dev commands
- Run server: `python -m wispr_dragon --server`
- Run UI: `wispr_dragon --ui` (installed script entrypoint)
- Launch CLI main: `python -m wispr_dragon`

High-level architecture
- Audio capture: `wispr_dragon/audio/` (PulseAudio or network capture)
- VAD: `wispr_dragon/audio/vad.py` (Silero VAD)
- Engines: `wispr_dragon/engine/` (subclass `engine/base.py`)
  - Local: faster-whisper, openai-whisper
  - Cloud: openai API engine
- Processing: `wispr_dragon/correction/` (hotwords, user dictionary, post-processing)
- Output / injection: `wispr_dragon/output/` (Windows-focused injection helpers)
- Modes & UI: `wispr_dragon/modes/`, `wispr_dragon/ui/` (dictation box, correction UI)
- Server/client: `server/` and `client/` directories for WebSocket audio stream and client capture/inject logic

Key repo conventions (important for Copilot tasks)
- New STT engines: subclass `wispr_dragon/engine/base.py`, register in `wispr_dragon/engine/__init__.py`, and add an optional-dependency extra in `pyproject.toml` under `[project.optional-dependencies]`.
- Config: primary runtime config is `~/.wispr_dragon/config.yaml`. Prefer adding defaults to `config.py` and validating with `tests/test_config_validation.py` when changing schema.
- Cross-platform injection: `output/text_injector.py` and `client/windows_injector.py` are Windows-first. Linux/macOS injectors are not complete — changes here require manual cross-platform verification.
- Tests: E2E tests live in `tests/` and may spin up real server+client; run them in WSL2 or a Linux environment to avoid audio/OS differences.
- PR/commit titles: follow `<scope>: <imperative>` (e.g., `client: add Linux text injector via ydotool`). See `.claude/commands/ship.md` for the ship gate procedure used by maintainers.
- Secrets: never commit API keys. OpenAI key is expected from `OPENAI_API_KEY` env var or `~/.wispr_dragon/config.yaml` (which is gitignored).
- Repo hygiene: scratch and session-note files sometimes appear at repo root; the cleanup workflow moves them to `docs/dev-notes/` or deletes them. Avoid adding new root scratch files.

Files of interest for assistant guidance
- `README.md` — user-facing install, config, and usage details
- `CLAUDE.md` — design context and agent delegation guidance
- `.claude/commands/ship.md` — project's pre-commit gate and expectations for tests/review

AI assistant integrations found
- CLAUDE.md and `.claude/commands/ship.md` contain guidance the maintainers use for agent delegation. Consult them when making process or automation changes.

When changing behavior
- Update `tests/` with focused tests covering the change (unit first; E2E only for integration parts)
- If adding a new engine or optional dependency, add an extra in `pyproject.toml` and a short example in `README.md` (dev install line)

If you need more context
- Start by reading `README.md` and `CLAUDE.md` for product vision and invariants.
- Use `pytest -q tests/<path>::<testname>` to verify a focused change locally.

--
Generated: concise Copilot guidance for repository-level edits and sessions. Adjust or request additions (CI/lint automation, MCP servers) as needed.
