# Linux /dev/uinput direct fallback

## Problem

`xdotool` and `ydotool` both depend on a display server. Headless sessions, SSH-with-X-forwarding, kiosks, accessibility setups — no display server, no injection.

## Solution

Direct `/dev/uinput` access via `python-evdev`:

```python
from evdev import UInput, ecodes as e

class UInputInjector:
    def __init__(self):
        caps = {e.EV_KEY: list(range(e.KEY_RESERVED + 1, e.KEY_MAX))}
        self.ui = UInput(events=caps, name="wispr-dragon-virtual-kbd")

    def inject(self, text: str) -> bool:
        for ch in text:
            scancode = _char_to_scancode(ch)  # layout-aware mapping
            self.ui.write(e.EV_KEY, scancode, 1)
            self.ui.write(e.EV_KEY, scancode, 0)
            self.ui.syn()
        return True
```

Requires the user to be in the `input` group (same as `ydotool`). Best as a last-resort fallback after xdotool/ydotool both fail.

## Effort

Small. Trickier piece is layout-aware scancode mapping — `python-xkbcommon` does this, but only with a layout database available. For US-QWERTY it's a hardcoded table.
