# Wayland vs X11 dispatch

## Problem

Linux split-brain: X11 sessions can use `xdotool` (simple, no daemon). Wayland sessions need `ydotool` (daemon, /dev/uinput permission). Hyprland, Sway, GNOME-Wayland, KDE-Wayland all handle focus differently.

## Solution

Detect at startup, log loudly:

```python
def detect_display_server() -> str:
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "headless"
```

Dispatch to the injector + focus-capture helper for that server. Log the detected server on startup so the user sees `Display: wayland (sway)` in the log when something breaks.

Per-compositor focus-capture quirks (Sway via `swaymsg`, Hyprland via `hyprctl`, generic Wayland via … not much) live in their own helpers.

## Effort

Small. Covered partially by [linux-ydotool-injector](linux-ydotool-injector.md); break out if Sway/Hyprland special cases pile up.
