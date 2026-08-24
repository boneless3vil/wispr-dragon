# Wispr Dragon — Ideas Index

Ranked roadmap of features, fixes, and bets. Generated 2026-06-01 from current repo state.

## Recommended order of attack

You asked which of the four scopes to do first. My ranking:

1. **STT quality & engine work** (`01-stt-quality/`) — the product's claim is "best speech recognition software ever." Latency, accuracy, and the missing Wispr cloud backend are foundational. Everything else compounds on top of a fast, accurate transcript.
2. **Cross-platform client** (`02-cross-platform/`) — CLAUDE.md flags this as the active expansion area. Today the app is Windows-only at the injector layer; Linux/macOS users get a server but no working dictation. Unblocks a big chunk of the addressable userbase.
3. **Dragon 16 parity gaps** (`03-dragon-parity/`) — this is what the product *is* per CLAUDE.md. Several files referenced in CLAUDE.md (`ui/dictation_box.py`, `ui/macro_editor.py`) don't actually exist yet. Building these gives the product its identity.
4. **Differentiators Dragon doesn't have** (`04-differentiators/`) — LLM post-processing, semantic commands, diarization. These are the "better than Dragon" plays. Worth doing last, once parity exists to differentiate *from*.

Bugs & hygiene (`05-bugs-and-hygiene/`) sit alongside everything — pick off as you touch the relevant files.

## Reality check

While surveying the repo I noticed a few mismatches between CLAUDE.md and the actual code. They're worth knowing before you commit to a plan:

- CLAUDE.md says **Wispr cloud** is a primary engine — there is no Wispr engine in `engine/`, and `EngineConfig.backend` doesn't list it. See [wispr-cloud-engine](01-stt-quality/wispr-cloud-engine.md).
- CLAUDE.md references `ui/dictation_box.py` and `ui/macro_editor.py` — neither file exists. See [dictation-box](03-dragon-parity/dictation-box.md) and [command-vocabulary-browser](03-dragon-parity/command-vocabulary-browser.md).
- CLAUDE.md says modes include **dictation, command, spelling, numbers** — only `command_mode.py` exists. See [modes-spelling-numbers](03-dragon-parity/modes-spelling-numbers.md).
- CLAUDE.md says **system tray + floating dictation box** — no tray code anywhere. See [dragonbar-system-tray](03-dragon-parity/dragonbar-system-tray.md).

This isn't criticism; it's just the gap between vision and code. The ideas below are organized to close it.

---

## 01 — STT quality & engine work

Foundational. Do first.

- [streaming-partials](01-stt-quality/streaming-partials.md) — **DEEP**. Today the pipeline waits for VAD silence before transcribing. Add partial-result streaming so the user sees text appear while they're still talking.
- [wispr-cloud-engine](01-stt-quality/wispr-cloud-engine.md) — **DEEP**. Vision says Wispr cloud is the primary backend; it's not implemented. Wire it up behind the existing `TranscriptionEngine` interface.
- [engine-fallback-chain](01-stt-quality/engine-fallback-chain.md) — Auto-fallback when cloud is down or rate-limited. Cloud → local → degraded.
- [accuracy-regression-suite](01-stt-quality/accuracy-regression-suite.md) — Fixed audio corpus + WER scoring on every PR. Catches accuracy drift before users do.
- [vad-tuning-presets](01-stt-quality/vad-tuning-presets.md) — `silence_duration_ms=500` is conservative. Add presets for "fast dictation," "thinking out loud," and "noisy room."
- [beam-size-adaptive](01-stt-quality/beam-size-adaptive.md) — Default beam_size=10 is heavy. Drop to 5 for short utterances, 10+ for long.
- [hotword-prompt-engineering](01-stt-quality/hotword-prompt-engineering.md) — `hotwords` + `initial_prompt` are wired but underused. Surface them in settings UI with domain templates (medical, legal, code).

## 02 — Cross-platform client

Active expansion area per CLAUDE.md.

- [linux-ydotool-injector](02-cross-platform/linux-ydotool-injector.md) — **DEEP**. The Wayland/X11 reality, why `ydotool` over `xdotool`, daemon-permission gotchas.
- [macos-cgevent-injector](02-cross-platform/macos-cgevent-injector.md) — **DEEP**. CGEvent + Accessibility prompt, secure input handling, code signing.
- [platform-dispatch-refactor](02-cross-platform/platform-dispatch-refactor.md) — Pull the `sys.platform` checks behind a `TextInjector` factory so adding platforms is one file.
- [wayland-vs-x11](02-cross-platform/wayland-vs-x11.md) — Detect display server, route to the right injector.
- [macos-accessibility-permission](02-cross-platform/macos-accessibility-permission.md) — First-run UX for granting accessibility access.
- [linux-input-uinput](02-cross-platform/linux-input-uinput.md) — Fallback for headless / no-Wayland-session cases via /dev/uinput.

## 03 — Dragon 16 parity gaps

Identity-defining features. Several are stubs or absent.

- [dragonbar-system-tray](03-dragon-parity/dragonbar-system-tray.md) — **DEEP**. No tray code exists. The mic-state indicator + quick mode switch lives here.
- [dictation-box](03-dragon-parity/dictation-box.md) — **DEEP**. Referenced in CLAUDE.md as `ui/dictation_box.py` but file is missing. Floating buffer for apps that don't accept direct injection.
- [spoken-alternates-correct-that](03-dragon-parity/spoken-alternates-correct-that.md) — **DEEP**. n-best from the engine + "Correct that" + numbered selection. The single most-loved Dragon feature.
- [mic-state-model](03-dragon-parity/mic-state-model.md) — Off / standby / hot state machine with one source of truth, surfaced in tray, UI, and hotkeys.
- [command-vocabulary-browser](03-dragon-parity/command-vocabulary-browser.md) — UI for `commands.yaml` + user dictionary. Currently you edit YAML by hand.
- [modes-spelling-numbers](03-dragon-parity/modes-spelling-numbers.md) — Add spelling mode and numbers mode alongside the existing command/dictation split.
- [numpad-plus-hotkey](03-dragon-parity/numpad-plus-hotkey.md) — Dragon's muscle-memory default as a one-line config option.
- [learn-from-correction](03-dragon-parity/learn-from-correction.md) — Auto-bump hotwords when the user keeps correcting the same misrecognition.

## 04 — Differentiators (beyond Dragon 16)

Once parity exists, these are the "why Wispr Dragon over Dragon" plays.

- [llm-post-processor](04-differentiators/llm-post-processor.md) — **DEEP**. Drop in a small LLM pass that fixes punctuation, capitalization, and disfluencies. Dragon can't do this.
- [semantic-commands](04-differentiators/semantic-commands.md) — **DEEP**. "Make that more formal," "turn this into a list," "fix the grammar." Voice commands that need understanding, not pattern-matching.
- [voice-profile-adaptive-lm](04-differentiators/voice-profile-adaptive-lm.md) — Per-user prompt that accumulates the user's vocabulary, names, and phrasings over time.
- [auto-mode-classifier](04-differentiators/auto-mode-classifier.md) — Stop making the user say "command mode" — classify each utterance as dictation, command, or correction.
- [diarization](04-differentiators/diarization.md) — Multi-speaker tagging for meetings.
- [multilingual-auto-detect](04-differentiators/multilingual-auto-detect.md) — Whisper supports it; just expose it.
- [nato-spelling-mode](04-differentiators/nato-spelling-mode.md) — "Alpha, bravo, charlie" → "abc". Cheap, beloved.
- [private-mode-no-cloud](04-differentiators/private-mode-no-cloud.md) — Hard switch that disables all network engines. Sells to compliance-bound users.

## 05 — Bugs & hygiene

Pick off when you touch the relevant files.

- [streaming-buffer-overflow](05-bugs-and-hygiene/streaming-buffer-overflow.md) — VAD has a max-buffer guard but flushes mid-utterance; that produces a cut transcript.
- [auth-reconnect-hardening](05-bugs-and-hygiene/auth-reconnect-hardening.md) — CLAUDE.md flags a prior reconnect-storm-on-auth-failure regression. Add a test.
- [config-migration-tool](05-bugs-and-hygiene/config-migration-tool.md) — Two config dirs (`.wispr-dragon` and `.wispr_dragon`) coexist with implicit fallback. One-shot migration command, then drop the fallback.
- [repo-cleanup-scratch-docs](05-bugs-and-hygiene/repo-cleanup-scratch-docs.md) — `SESSION_NOTES_*`, `PHASE_*` files at root. CLAUDE.md already names the cleanup agent.
- [venv-tracked-issue](05-bugs-and-hygiene/venv-tracked-issue.md) — `venv/` appears under the working tree. Confirm it's gitignored.
- [test-coverage-gaps](05-bugs-and-hygiene/test-coverage-gaps.md) — No tests for VAD, websocket server, pipeline_runner, audio_capture.
- [pyproject-wispr-extra](05-bugs-and-hygiene/pyproject-wispr-extra.md) — Add a `wispr-cloud` extra to `[project.optional-dependencies]` when the engine lands.
- [error-toasts-not-logs](05-bugs-and-hygiene/error-toasts-not-logs.md) — Most failure paths only log. UI users never see them.
