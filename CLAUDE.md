# Wispr Dragon — Agent Context

Speech recognition app: Linux-based WebSocket server + cross-platform desktop clients (Linux/macOS/Windows). Python 3.11+, PyQt6 UI, pluggable STT backends.

## Product vision

- **STT engines**: Wispr (cloud) and faster-whisper (local) as primary backends, with OpenAI API and openai-whisper as fallbacks.
- **UX reference**: Dragon NaturallySpeaking 16.1 is the model for capabilities and interaction patterns we're emulating. When designing UI or commands, the question to ask is "how does Dragon 16 do this?" Specifically the parts worth porting in spirit (not literally):
  - **DragonBar** equivalent → our system tray + floating dictation box.
  - **Mic state model** → off / standby / hot, with a clear visual indicator.
  - **Dictation Box** for apps that don't accept direct injection (Dragon's solution to focus/inject gotchas) — we have `ui/dictation_box.py`.
  - **Correction window** — already exists in `ui/correction_window.py`. Match Dragon's flow: spoken alternate list, "Correct that", learn the fix.
  - **Command browser / vocabulary editor** — partially in `ui/macro_editor.py`. Dragon's split between Commands and Vocabulary is a useful model; reflect it in the UI even if storage is unified.
  - **Modes**: dictation, command, spelling, numbers. We have `modes/` — extend it as we add Dragon-equivalent modes.
  - **Hotkeys**: push-to-talk + toggle (already in `client/hotkey.py`). Dragon's "+ on numpad" is the muscle-memory standard for many users — consider it as a default.
- **What we explicitly are NOT copying**: Dragon's proprietary file formats, profile system internals, or DLLs. We design our own equivalents.
- **Product lineup — one codebase, three builds** (decided 2026-10-19; never separate product branches):
  1. **Windows standalone** — client + recognizer on the same Windows PC, running on its own GPU; no Linux server needed.
  2. **Linux standalone** — client + recognizer on one Linux machine.
  3. **Client + server** — thin clients (Windows / macOS / Linux) talking to the Linux recognition server.

  All three get the full feature set (modes, commands, macros, spelling/numbers, correction, dictation box). "Standalone" = the client running a local recognizer, so the builds differ only in packaging. Roadmap: `ideas/protocol-and-client-commands.md`.

## Architecture

```
wispr_dragon/
  server/      WebSocket server, audio receiver, pipeline runner   (Linux/WSL2)
  client/      Cross-platform client: capture → stream → inject     (Lin/Mac/Win)
  engine/      Pluggable STT: faster-whisper, openai-api, openai-whisper
  audio/       Mic capture + Silero VAD
  ui/          PyQt6 dictation box, settings, macro editor, correction, tray
  output/      Text injection for the Linux/WSLg desktop app (xdotool / xclip / wl-clipboard)
  modes/       Command vs dictation mode
  correction/  Post-processing: hotwords, dictionary
  macros/      Voice-triggered macros (hash-pinned, time-limited scripts — not a sandbox)
tests/         pytest, includes server/client E2E
scripts/       Benchmarks, audio test utilities
```

## Stack & invariants

- **Python 3.11+**, packaged via `pyproject.toml`, extras: `gui`, `server`, `client`, `openai-api`, `whisper-fallback`, `dev`.
- **WebSocket protocol** (`websockets >=12,<13`) for server↔client audio + transcript stream. Auth required; reconnect storms on auth failure were fixed once — don't reintroduce.
- **Audio**: `sounddevice` (PortAudio) for capture, Silero VAD for endpointing. WSL2 needs PulseAudio or network audio fallback.
- **STT engines** implement `engine/base.py` interface. `gpu_advisor.py` recommends model size based on hardware.
- **Cross-platform client** is the active expansion area. Today the client injects only on Windows (`client/windows_injector.py`, clipboard paste by default); `output/text_injector.py` serves the Linux desktop app only. Linux/macOS client injectors are TBD (`ydotool` on Linux, CGEvent on macOS).
- **Tests**: `pytest tests/ -v`. E2E tests in `test_server_client_e2e.py` spin up real server+client. `tests/conftest.py` points HOME at a temp dir, so tests never touch real user data.
- **Version**: single source is `wispr_dragon/__init__.py` (`__version__`); pyproject reads it dynamically.

## Dev environment

- Server dev runs in **WSL2 Ubuntu** (`/home/jon/wispr_dragon`) from the repo venv: `source venv/bin/activate` (Python 3.13; interpreter `/home/jon/wispr_dragon/venv/bin/python`). It holds the working GPU/audio stack — CUDA-12 torch (`cu126` index) and sounddevice linked to the custom PulseAudio-enabled PortAudio in `/usr/local/lib`. Don't use conda for this project (its PortAudio is ALSA-only and shadows that build). CI also tests 3.11.
- Run server: `python -m wispr_dragon --server`. Run UI: `wispr_dragon --ui`. Both honor `~/.wispr_dragon/config.yaml`.
- Lint: CI enforces `ruff check .` (rules in `pyproject.toml`). Typecheck: none enforced yet — prefer `mypy --strict` on new modules only.

## Conventions

- New STT backends: subclass `engine/base.py`, register in `engine/__init__.py`, add to `[project.optional-dependencies]` as its own extra.
- New client platform: mirror the structure of `client/windows_injector.py` and `client/hotkey.py`. Keep platform code behind `sys.platform` dispatch in `client/app.py`.
- Config schema lives in `config.py` with validation. Update `tests/test_config_validation.py` whenever the schema changes.
- Don't commit secrets (OpenAI API keys live in env var `OPENAI_API_KEY` or `~/.wispr_dragon/config.yaml` which is gitignored).

## Repo hygiene

The repo accumulated phase-tracking and session-notes files during early development (`SESSION_NOTES_*`, `PHASE_*_SUMMARY`, `PUSH_TO_GITHUB.md`, etc.). These are dev scratch, not product docs. The **cleanup** agent owns sorting them. Don't let new ones land at repo root — put scratch in `docs/dev-notes/` (gitignored) or just delete after the work merges.

## Branch & PR flow

- Development happens on the `test` branch; `main` only receives `--no-ff` merges of `test` once tests pass and the user confirms. CI runs on pushes to `main`/`test` and on PRs to `main`.
- PR titles: `<scope>: <imperative>` — e.g. `client: add Linux text injector via ydotool`.
- Before opening a PR: `pytest tests/ -v` must pass; for cross-platform changes, the **cross-platform-check** invariant in `.claude/commands/ship.md` applies.
- Branching: work on `test` (short-lived feature branches off `test` are fine for big changes). The **git-ops** agent handles branch creation, PR opening, and release tagging via `gh`.

## Where to delegate

For non-trivial work, delegate to specialist subagents (see `.claude/agents/`):

- **architect** — design before code on protocol, engines, cross-platform abstraction, or any Dragon-equivalent UX feature.
- **server-dev** — `server/`, `engine/`, `modes/`, `correction/`, `macros/`.
- **client-dev** — `client/`, `ui/`, `output/`. Always consider all three platforms.
- **audio-stt** — audio pipeline, VAD, engine selection, GPU advisor, benchmarks.
- **refactor** — restructuring code without changing behavior (extract, move, rename, split modules).
- **cleanup** — sorting out repo cruft: scratch docs, gitignored-but-tracked files, dead code.
- **git-ops** — branches, PRs, releases, `gh` operations.
- **test-runner** — pytest execution (read-only on source).
- **code-reviewer** — pre-commit diff review (read-only).
- **research** — Whisper / WebSocket / platform-API docs, Dragon 16 behavior references.
