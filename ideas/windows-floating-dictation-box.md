# Windows floating dictation box (Dragon-style "Dictation Box")

**Goal:** bring the dictation-box UX to the **Windows client**. A settings toggle;
when on, activating the mic while a text field is focused pops up a floating box
at that field. You dictate into the box (see + correct), then it injects into the
field. Also rescues fields where direct injection fails.

## Decisions (Jon, 2026-07-15)
- **Trigger:** **mic-on in a text field** — box appears only when the hotkey/mic
  is active AND an editable field is focused (not on every focus).
- **Behavior:** **stage then inject** — dictate into the box, correct, then it
  types/pastes into the focused field (via the existing paste injector).
- Gated by a **settings toggle** (off by default).

## The enabling tech: Windows UI Automation (UIA)
Detecting "there's a text field" in any app is the crux.
- Subscribe to UIA **focus-change events**; check the focused element is editable
  (ControlType Edit/Document, supports Text/Value pattern).
- Get the element's (or caret's) **screen rectangle** to position the box next to
  the field; fall back to near-cursor if no rect.
- Candidate deps: `uiautomation` (yinkaisheng) or `pywinauto`/comtypes UIA.
  Windows-only, lazy-imported so the package stays importable elsewhere.
- Coverage: native + most browser/Electron apps expose UIA; some custom-drawn
  apps (games, a few Electron oddballs) don't — box just won't auto-trigger there
  (document this; user can still use normal dictation).

## Flow
1. Feature enabled + hotkey pressed (mic on).
2. UIA reports focused editable element + rect → show floating box anchored there.
3. Live transcription streams into the box (same as WSL `--ui` box).
4. On Post (Enter): inject staged text into the field with the paste injector
   (`windows_injector.py`), restoring the caret/field focus first.
5. Box closes on Post/Esc; hidden when mic off.

## Rough file plan (Windows client)
- New `wispr_dragon/client/uia_focus.py` — UIA focus watcher: `is_text_field()`,
  `focused_field_rect()`, focus-changed callback. Lazy `comtypes`/`uiautomation`.
- New `wispr_dragon/client/floating_box.py` — small always-on-top PyQt6 box
  (reuse ideas from `ui/dictation_box.py`) positioned at a screen rect; shows live
  text + correct; emits final text.
- Edit `client/app.py` — when `config.floating_box` enabled and hotkey active,
  query UIA; if a field is focused, show the box; route transcripts to it; on
  Post, inject into the (re-focused) field.
- Config: `floating_box_enabled` (client config.json) + Settings-dialog toggle.
- Deps: new `uia`/client extra (`uiautomation` or `comtypes`).

## Edge cases
- Focus changes while dictating (user clicks away) → keep box anchored to the
  original field; inject there on Post (re-focus it first), or cancel if gone.
- Fields UIA can't see → no auto-box; fall back to normal client dictation.
- Multi-monitor / DPI scaling → position using physical screen coords from UIA.
- Password fields → skip (don't dictate into masked inputs).

## Full Dragon-16.1 capabilities (Jon, 2026-07-15)
The box must have **all** the Dragon Dictation Box capabilities, not just plain
dictation: **correction, spoken formatting, modes (command/spelling/numbers),
"scratch that", "correct that"**, etc.

**Architectural consequence — the big one:** those command/mode features currently
live ONLY in the local desktop app's orchestrator (`modes/orchestrator.py`,
`modes/mode_manager.py`) and the **server pipeline deliberately skips them** — the
client/server path only does transcribe + post-process. So this feature REQUIRES
routing the server's utterance transcription through the command/mode engine so
the client can receive not just text but command outcomes (mode switch, undo,
correction trigger, keystroke/macro).

What already works in the client path vs what's missing:
- ✅ **Spoken formatting** (period/comma/new line) — server `post_processor` already applies it.
- ✅ **"correct that"** — client has a correction dialog + `learn_correction` to the server.
- ✅ **Custom vocabulary / auto-caps** — server post-processing.
- ❌ **Modes** (command/spelling/numbers), **"scratch that"/undo**, **macros** —
  server pipeline doesn't run the orchestrator; these never reach the client.

So this is really **two coupled pieces**:
1. **Floating box UI** (UIA text-field detection + anchored PyQt box) — this file.
2. **Bring the command/mode engine into the client/server path** — a larger
   server + protocol change (route `process_utterance` through the orchestrator,
   send command outcomes to the client). Prerequisite for full parity.

Recommend architect-designing #2 (the pipeline/protocol change) before building
the box UI, since the box's feature set depends on it. Scope as a phased build:
box UI + formatting/correction (works today) first, then modes/commands/scratch as
#2 lands.
