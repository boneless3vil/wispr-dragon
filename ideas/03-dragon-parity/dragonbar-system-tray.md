# DragonBar (system tray)

## Problem

CLAUDE.md says:

> **DragonBar** equivalent → our system tray + floating dictation box.
> **Mic state model** → off / standby / hot, with a clear visual indicator.

Today there's no system tray code anywhere in the repo. Users have no persistent UI surface: the dictation box only appears during dictation, settings is a modal dialog, and there's no quick mic toggle or mode switch outside of hotkeys.

For a tool the user wants running all day, a tray icon is the *first* UI piece — it's where the mic state, the mode, and the "open settings" button live.

## Solution

New `wispr_dragon/ui/tray.py` using `QSystemTrayIcon` from PyQt6.

### State-driven icon

The icon reflects the current mic state. Three SVG variants under `assets/tray/`:

- `tray-off.svg` (grey crossed mic) — service off.
- `tray-standby.svg` (outlined mic) — service on, push-to-talk listening for hotkey.
- `tray-hot.svg` (filled red mic) — actively transcribing.

Plus a fourth, `tray-error.svg`, for "engine failed to load" / "websocket disconnected" — clicking it surfaces the error toast/log.

### Menu structure (mirror Dragon's DragonBar)

```
● Wispr Dragon — Hot
  ───────────────────
  Microphone:        On / Off          [hotkey]
  Mode:              Dictation ▸
                       • Dictation
                       • Command
                       • Spelling
                       • Numbers
  ───────────────────
  Open dictation box                   [Ctrl+Shift+D]
  Show correction window               [Ctrl+Shift+C]
  Vocabulary editor…
  ───────────────────
  Settings…
  Server status: Connected (ws://… )
  ───────────────────
  About
  Quit
```

The mic state, mode, and server status are *live* (rebuild the menu on state change, or update individual `QAction`s). The hotkeys shown next to items are sourced from `UIConfig` so users see their actual binding, not a hardcoded default.

### State bus

Right now mic state lives implicitly in `hotkey.py`, transcription state in `transcription_worker.py`, mode in `mode_manager.py`. The tray needs a single source of truth, so introduce a `AppState` `QObject`:

```python
# wispr_dragon/ui/app_state.py
class AppState(QObject):
    mic_state_changed = pyqtSignal(str)   # "off" | "standby" | "hot"
    mode_changed = pyqtSignal(str)        # "dictation" | "command" | ...
    server_status_changed = pyqtSignal(str, str)  # status, detail
    error = pyqtSignal(str)
```

Tray, dictation box, hotkey manager, and websocket client all read+write through this. See [mic-state-model](mic-state-model.md) for the state machine itself.

### Linux/macOS tray quirks

- **GNOME**: hides legacy `QSystemTrayIcon` by default. Document the AppIndicator extension or fall back to a launcher-pinned window.
- **macOS**: tray icon goes in the menu bar. The icon must be a template image (single-color, 22x22 @1x / 44x44 @2x) so macOS auto-inverts in dark mode. Don't ship a color icon for macOS — it will look broken.
- **Windows**: standard tray works fine; right-click for menu.

## Affected files

- New `wispr_dragon/ui/tray.py`.
- New `wispr_dragon/ui/app_state.py`.
- New `wispr_dragon/assets/tray/*.svg` (off, standby, hot, error; plus a macOS-template variant).
- `wispr_dragon/client/__main__.py` — start tray on launch, keep app alive in tray.
- `wispr_dragon/client/hotkey.py` — emit through `AppState` rather than calling injector directly.
- `wispr_dragon/modes/mode_manager.py` (imported by `pipeline_runner.py`) — emit `mode_changed`.
- Settings UI — add "Hide tray icon" preference for users who hate trays.

## Effort

Medium. Tray itself is one afternoon. The state-bus refactor is what takes time, because today state is implicit and scattered. Doing the state bus first pays off for almost every other parity feature.

## Gotchas

- **App must not quit when last window closes.** Set `QApplication.setQuitOnLastWindowClosed(False)` once the tray is up, otherwise closing the settings dialog kills the daemon.
- **Tray needs an event loop.** If the client process today is mostly a CLI worker, you'll need to spin a `QApplication` in the main thread and run the websocket loop on a worker — this is the standard PyQt + asyncio pattern via `qasync`.
- **Icon refresh on theme change.** PyQt6 supports `QIcon.setIsMask(True)` for template behavior, but only on macOS; on Linux you have to ship light/dark variants and switch on `palette().window().color().lightness()`.
