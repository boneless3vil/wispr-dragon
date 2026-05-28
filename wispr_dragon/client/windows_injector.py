"""Windows text injection via the SendInput API.

Types Unicode text directly into whatever window currently has keyboard focus,
using synthesized keystrokes (KEYEVENTF_UNICODE). This does not touch the
clipboard and works in any standard text field regardless of keyboard layout.

The module imports cleanly on any platform — the ctypes structures are just
memory layouts — but :meth:`WindowsTextInjector.inject` is a no-op anywhere
other than native Windows.
"""

from __future__ import annotations

import ctypes
import logging
import struct
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

# --- SendInput constants ---------------------------------------------------
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_VK_RETURN = 0x0D

# ULONG_PTR is pointer-sized; ctypes.wintypes does not define it.
_ULONG_PTR = ctypes.c_size_t


# --- INPUT structure -------------------------------------------------------
# The union holds all three input kinds so sizeof(INPUT) matches the real
# Win32 type — SendInput rejects the call otherwise. Only `ki` is ever used.
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    )


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    )


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


def _key_event(vk: int, scan: int, flags: int) -> INPUT:
    """Build one keyboard INPUT event."""
    return INPUT(
        type=_INPUT_KEYBOARD,
        union=_INPUTUNION(
            ki=_KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
        ),
    )


def _text_to_inputs(text: str) -> list:
    """Convert text into a flat list of key-down/key-up INPUT events.

    Iterates UTF-16 code units, so characters outside the BMP (e.g. emoji) are
    emitted as their surrogate pair automatically. Line breaks are sent as the
    Return virtual key rather than as a literal character.
    """
    events: list = []
    for (unit,) in struct.iter_unpack("<H", text.encode("utf-16-le")):
        if unit in (0x0A, 0x0D):  # \n or \r -> Return keypress
            events.append(_key_event(_VK_RETURN, 0, 0))
            events.append(_key_event(_VK_RETURN, 0, _KEYEVENTF_KEYUP))
        else:
            events.append(_key_event(0, unit, _KEYEVENTF_UNICODE))
            events.append(_key_event(0, unit, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
    return events


class WindowsTextInjector:
    """Types Unicode text into the focused Windows window via SendInput."""

    def __init__(self):
        self.available = sys.platform == "win32"
        self._user32 = None
        if not self.available:
            logger.warning(
                "WindowsTextInjector is inert off Windows (platform=%s)", sys.platform
            )
            return
        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._user32.SendInput.argtypes = (
                wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int,
            )
            self._user32.SendInput.restype = wintypes.UINT
        except Exception as e:  # pragma: no cover - Windows-only path
            logger.error("Could not bind user32.SendInput: %s", e)
            self.available = False

    def inject(self, text: str) -> bool:
        """Type ``text`` into whatever window currently has keyboard focus.

        Returns:
            True if every keystroke was delivered, False otherwise (empty
            text, not on Windows, or SendInput was blocked).
        """
        if not text or not self.available:
            return False

        events = _text_to_inputs(text)
        if not events:
            return False

        count = len(events)
        array = (INPUT * count)(*events)
        try:
            sent = self._user32.SendInput(count, array, ctypes.sizeof(INPUT))
        except Exception as e:  # pragma: no cover - Windows-only path
            logger.error("SendInput call failed: %s", e)
            return False

        if sent != count:
            # A short count usually means UIPI blocked input to a window
            # running at a higher integrity level (e.g. an elevated app).
            logger.warning(
                "SendInput delivered %d/%d events (WinError %d)",
                sent, count, ctypes.get_last_error(),
            )
            return False
        return True
