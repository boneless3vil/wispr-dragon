# Linux text injector

## Problem

`wispr_dragon/client/windows_injector.py` is the only injector. `output/text_injector.py` is the wrapper. On Linux, dictation produces a transcript but nothing gets typed. CLAUDE.md flags this as the active expansion area.

The complication: Linux has two display servers (X11 and Wayland) and neither has one canonical injection API.

## Solution

Two backends behind a unified `LinuxTextInjector`:

### Backend 1: ydotool (Wayland-friendly)

`ydotool` writes to `/dev/uinput` via a privileged daemon, so it works under Wayland *and* X11. The catch: the daemon (`ydotoold`) needs to be running, and the user has to be in a group with `/dev/uinput` access (commonly `input`).

```python
import subprocess

class YdotoolInjector:
    def __init__(self):
        self.available = shutil.which("ydotool") is not None
        # Check daemon running by attempting a no-op key sequence.

    def inject(self, text: str) -> bool:
        if not text or not self.available:
            return False
        try:
            subprocess.run(
                ["ydotool", "type", "--", text],
                check=True, timeout=5, capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("ydotool inject failed: %s", e)
            return False
```

### Backend 2: xdotool (X11 only, simpler)

If `XDG_SESSION_TYPE=x11`, prefer `xdotool` — no daemon, no group fiddling. Same shell-out pattern.

### Dispatch

```python
def make_linux_injector() -> Optional[TextInjector]:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    if session == "x11" and shutil.which("xdotool"):
        return XdotoolInjector()
    if shutil.which("ydotool"):
        return YdotoolInjector()
    return None
```

This goes in a new `wispr_dragon/client/linux_injector.py` mirroring `windows_injector.py`.

## First-run UX

Most users won't have `ydotool` or `xdotool` installed. The app should:

1. Detect missing binaries at startup.
2. Show a one-time dialog: "Wispr Dragon needs ydotool (or xdotool on X11) to type into other apps. Install with: `sudo apt install ydotool` (then add yourself to the `input` group)."
3. Offer a "Test typing" button that injects "hello world" into a focused window so the user knows it works.
4. Detect the daemon-not-running case specifically and offer a one-click `systemctl --user start ydotoold` or fallback systemd-user unit.

A working button is worth 100 lines of docs.

## Affected files

- New `wispr_dragon/client/linux_injector.py`.
- `wispr_dragon/output/text_injector.py` — platform dispatch (see [platform-dispatch-refactor](platform-dispatch-refactor.md)).
- `wispr_dragon/client/app.py` (or wherever the platform branch lives) — wire it in.
- New `tests/test_linux_injector.py` — mock subprocess, cover both backends and the dispatch.
- `README` / install docs — system-package dependencies.

## Effort

Medium. The injector code is short. The UX around "ydotool isn't installed" is what takes time, and it's where most users will give up if you skip it.

## Gotchas

- **Wayland clipboard injection is brittle.** Don't fall back to `wl-copy` + paste — different compositors handle clipboard ownership differently.
- **Dead keys & IMEs.** If the user has a non-US layout, `ydotool type` honors it; `xdotool` doesn't always. Document.
- **Race with focus.** On Linux, sometimes the dictation box itself takes focus when shown. Inject must be deferred until the original app reclaims focus. Track `xdotool getactivewindow` (or `swaymsg`/`hyprctl`) before showing partials.
- **Headless / SSH sessions.** No display server → no injection. Detect and either disable typing or use uinput directly (see [linux-input-uinput](linux-input-uinput.md)).
