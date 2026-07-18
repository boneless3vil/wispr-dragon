# Numpad-plus hotkey default

## Problem

CLAUDE.md flags Dragon's "+ on numpad" as the muscle-memory standard for many users — but `client/hotkey.py` doesn't ship that as a default. Anyone migrating from Dragon will rebind, which is fine, but they'll complain that day 1 doesn't work like Dragon.

## Solution

Two presets in `UIConfig`:

```python
HOTKEY_PRESETS = {
    "dragon":  {"ptt": "kp_add", "toggle": "ctrl+shift+space"},
    "modern":  {"ptt": "ctrl+space", "toggle": "ctrl+shift+space"},
}
```

First-run setup asks: "Coming from Dragon? Pick the Dragon preset for familiar hotkeys." Defaults to "modern" otherwise.

## Effort

Trivial.
