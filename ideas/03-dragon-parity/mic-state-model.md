# Mic state model

## Problem

Mic state is implicit and scattered: `hotkey.py` knows about push-to-talk; `transcription_worker.py` knows about active transcription; the (future) tray needs to *display* state; the (future) dictation box needs to *react* to state. Without one source of truth, the UI will drift out of sync with reality.

## Solution

A small state machine in `wispr_dragon/ui/app_state.py` (introduced alongside [dragonbar-system-tray](dragonbar-system-tray.md)).

```
   ┌─────┐  user toggles on    ┌─────────┐  user holds PTT /
   │ OFF │ ───────────────────▶│ STANDBY │  toggles hot
   │     │◀───────────────────│         │ ─────────────────┐
   └─────┘  user toggles off  └─────────┘                 │
                                  ▲                         ▼
                                  │   PTT release /     ┌──────┐
                                  └────────────────────│ HOT  │
                                                        └──────┘

   ERROR overlay on any state — engine down, websocket disconnected.
```

```python
class MicState(str, Enum):
    OFF = "off"
    STANDBY = "standby"
    HOT = "hot"

class AppState(QObject):
    mic_state_changed = pyqtSignal(MicState)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._mic_state = MicState.OFF

    def set_mic_state(self, new: MicState):
        if new == self._mic_state:
            return
        self._mic_state = new
        self.mic_state_changed.emit(new)
```

Everything that *changes* state (hotkey, tray menu, settings panel "off at startup," websocket error handler) calls `set_mic_state`. Everything that *displays* state subscribes.

PTT vs toggle mode is a separate setting (`UIConfig.hotkey_mode = "toggle" | "ptt"`), not separate state — the state machine only cares about the resulting mic state.

## Affected files

- New `wispr_dragon/ui/app_state.py`.
- `wispr_dragon/client/hotkey.py` — emit through state.
- `wispr_dragon/client/__main__.py` — instantiate AppState as singleton.
- `wispr_dragon/ui/tray.py` (when built) — subscribe.
- `wispr_dragon/server/websocket_server.py` — emit error states.

## Effort

Small. Worth doing *before* the tray and dictation box, because both depend on it. Without this, you'll wire identical state into both and they'll drift.
