# Dictation box

## Problem

CLAUDE.md says:

> **Dictation Box** for apps that don't accept direct injection (Dragon's solution to focus/inject gotchas) — we have `ui/dictation_box.py`.

We don't. `wispr_dragon/ui/` has `settings_dialog.py`, `transcription_worker.py`, `correction_window.py`, `confirm_command.py`. No `dictation_box.py`.

The dictation box is one of Dragon's most-loved features and the single biggest reliability win for transcription. Apps where direct injection fails — web editors with custom input handling, Electron apps with weird focus management, password fields, secure-input contexts on macOS — all become usable through a side buffer the user dictates into, then transfers.

## Solution

New `wispr_dragon/ui/dictation_box.py` — a frameless, always-on-top, focus-stealable `QWidget` that:

1. Shows partial + final transcripts as they stream (see [streaming-partials](../01-stt-quality/streaming-partials.md)).
2. Buffers the full session text in a `QPlainTextEdit`.
3. Offers a "Transfer" button (and a `Ctrl+Enter` hotkey) that:
   - Stores current focus target (where the user *was* before opening the box).
   - Hides the box.
   - Restores focus to the original target.
   - Injects the buffer's contents (via the platform injector).
4. Offers "Discard," "Edit," and "Append to" modes.

### Layout

```
┌──────────────────────────────────────────────┐
│ ● Dictating  ·  Mode: Dictation  ·  ⚙        │
├──────────────────────────────────────────────┤
│ The quick brown fox jumps over                │
│ the lazy dog. ▌                               │
│                                                │
├──────────────────────────────────────────────┤
│  [Transfer ⏎]  [Discard]  [Edit]   ⤓ tray    │
└──────────────────────────────────────────────┘
```

Header shows live mic state, current mode, gear opens settings. Body is the buffer (partials in lighter grey, finals in normal weight). Footer is the transfer controls.

### Why a separate widget vs the correction window

`correction_window.py` is a *modal* dialog for fixing a single transcribed segment. The dictation box is a *persistent, always-available* surface for composing multi-sentence content. Different lifecycle, different focus semantics. Don't try to share them — keep correction modal, keep the dictation box persistent.

### Focus-target preservation

Hardest part. When the user activates dictation while focused in (say) a browser textarea:

1. **Capture the focused window/element** before the box appears. On Windows: `GetForegroundWindow` + `GetFocus`. On macOS: `NSWorkspace.activeApplication` and the focused element via Accessibility API. On Linux/X11: `xdotool getactivewindow`. Wayland: there's no good API; fall back to "use the last-active-non-Wispr window."
2. Show the box. The user dictates; partials/finals stream into the buffer.
3. On Transfer, restore focus to the captured window/element. Brief sleep (50 ms) for the OS to settle. Inject.
4. If focus restore fails, fall back to clipboard paste (`SetClipboardData` + `^V`) with a toast warning.

### Hotkey-to-show

Add a new hotkey binding in `UIConfig`: `dictation_box_shortcut`, default `Ctrl+Shift+D`. When pressed, toggle box visibility. The push-to-talk hotkey continues to control mic state independently.

## Affected files

- New `wispr_dragon/ui/dictation_box.py`.
- `wispr_dragon/client/hotkey.py` — add `dictation_box_shortcut` binding.
- `wispr_dragon/config.py` — extend `UIConfig` with the new shortcut + a `dictation_box_default_open` flag.
- `wispr_dragon/output/text_injector.py` — add `inject_after_focus_restore(window_handle, text)` helper.
- New platform-specific focus capture helpers under `client/{windows,macos,linux}_focus.py`.
- Tests: `tests/test_dictation_box.py` — focus capture mocked.

## Effort

Medium-large. The widget itself is small. The cross-platform focus capture/restore is where the platform-specific work piles up.

## Gotchas

- **Don't render into the dictation box AND inject simultaneously.** Pick one based on a config flag (`always_use_dictation_box`) or per-app rules (later: per-app injection allow/deny list).
- **Box must not steal focus on show** unless the user explicitly invoked it. When triggered by mic activation, show it with `Qt.WindowDoesNotAcceptFocus` so the user keeps typing in their target app.
- **High DPI**: position the box near the focused element if possible, or near the mouse cursor. Always-on-top widgets that materialize in the corner of screen 1 when the user is on screen 3 are aggravating.
- **Clipboard fallback** must restore the user's previous clipboard contents after paste, or you've made the app a clipboard-clobberer.
