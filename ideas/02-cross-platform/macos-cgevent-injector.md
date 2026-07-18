# macOS text injector

## Problem

Same as Linux — no macOS injection backend. Today the macOS client transcribes but doesn't type. macOS adds two wrinkles Linux doesn't have: the app must be granted **Accessibility** permission, and there's a separate "**Secure Input**" mode that blocks all synthetic events when the focused field is a password.

## Solution

Use the public CoreGraphics event API via `pyobjc` (`Quartz.CGEventCreateKeyboardEvent` + `CGEventKeyboardSetUnicodeString`).

```python
# wispr_dragon/client/macos_injector.py
from __future__ import annotations
import logging, sys

logger = logging.getLogger(__name__)

class MacOSTextInjector:
    def __init__(self):
        self.available = sys.platform == "darwin"
        self._quartz = None
        if self.available:
            try:
                from Quartz import (
                    CGEventCreateKeyboardEvent, CGEventKeyboardSetUnicodeString,
                    CGEventPost, kCGHIDEventTap,
                )
                self._fns = (
                    CGEventCreateKeyboardEvent,
                    CGEventKeyboardSetUnicodeString,
                    CGEventPost,
                    kCGHIDEventTap,
                )
            except ImportError:
                logger.error("pyobjc-framework-Quartz not installed")
                self.available = False

    def inject(self, text: str) -> bool:
        if not text or not self.available:
            return False
        CreateEvt, SetUnicode, Post, tap = self._fns
        for ch in text:
            down = CreateEvt(None, 0, True)
            up   = CreateEvt(None, 0, False)
            SetUnicode(down, 1, ch)
            SetUnicode(up,   1, ch)
            Post(tap, down)
            Post(tap, up)
        return True
```

Use `CGEventKeyboardSetUnicodeString` (the unicode-string variant) rather than virtual key codes — it works regardless of keyboard layout, like the Windows `KEYEVENTF_UNICODE` flow already in `windows_injector.py`.

## Accessibility permission

CGEvents only post if the app is in **System Settings → Privacy & Security → Accessibility**. First run will silently fail. Solution:

```python
def _check_accessibility() -> bool:
    from ApplicationServices import AXIsProcessTrustedWithOptions
    from CoreFoundation import CFDictionaryCreate
    opts = {"AXTrustedCheckOptionPrompt": True}
    return AXIsProcessTrustedWithOptions(opts)
```

Passing `AXTrustedCheckOptionPrompt=True` makes macOS show the permission dialog the first time. On subsequent runs, just check silently. If `False`, the UI should display: "Wispr Dragon needs Accessibility access to type. Open System Settings → Privacy & Security → Accessibility and enable Wispr Dragon."

## Secure Input handling

If the focused field is a password (Terminal in some configs, 1Password, login screens), macOS sets a system-wide `IsSecureEventInputEnabled` flag and silently drops your CGEvent posts. There's no way around it without entitlements that won't ship to a non-signed app.

Detect it and tell the user:

```python
from ApplicationServices import IsSecureEventInputEnabled
if IsSecureEventInputEnabled():
    show_toast("Secure Input is active — typing is blocked. Click outside the password field to dictate.")
```

This is one of the most common "Dragon doesn't work" bug reports on macOS. Surface it.

## Code signing & notarization

For shipped builds, the app must be:
- Code-signed with a Developer ID certificate.
- Notarized through Apple's notarization service.
- Listed in `Info.plist` with `NSAccessibilityUsageDescription`.

Otherwise Gatekeeper blocks the app from being granted Accessibility on most setups. This is a packaging concern, not a code one, but it lives on the critical path for shipping macOS.

## Affected files

- New `wispr_dragon/client/macos_injector.py`.
- `wispr_dragon/output/text_injector.py` — dispatch.
- New `tests/test_macos_injector.py` — mock pyobjc imports.
- `pyproject.toml` — add `pyobjc-framework-Quartz` and `pyobjc-framework-ApplicationServices` to a `macos` extra.
- Packaging scripts (future) — signing + notarization workflow.

## Effort

Medium. The injector is small. The permission flow, secure-input UX, and signing are most of the work.

## Gotchas

- **PyQt6 + pyobjc share the autorelease pool.** Keep `Quartz` imports lazy (inside `__init__`) — eager import in a non-Qt thread sometimes corrupts the pool.
- **Slow when typing fast.** `CGEventPost` per character is fine up to ~50 chars/sec. For longer paragraphs, batch with `CGEventCreateKeyboardEvent(None, 0, True)` then set a longer unicode string (the API supports up to 20 chars per event).
- **Apple Silicon vs Intel** — both fine with this API; no arch-specific code needed.
