"""Windows text injection.

Primary path is **clipboard paste**: set the focused app's expected text on the
clipboard and synthesize a single Ctrl+V. This is the method serious dictation
tools (Dragon, etc.) use, and it proved necessary in the field — some systems
run keyboard hooks / peripheral drivers that corrupt long bursts of synthesized
per-character keystrokes (dropped and auto-repeated characters), while a single
paste keystroke is unaffected. The original per-character ``SendInput`` path
(``KEYEVENTF_UNICODE``) is kept as a fallback for when the clipboard is
unavailable.

The module imports cleanly on any platform — the ctypes structures are just
memory layouts — but injection is a no-op anywhere other than native Windows.
"""

from __future__ import annotations

import ctypes
import logging
import struct
import sys
import time
from ctypes import wintypes
from typing import Optional

logger = logging.getLogger(__name__)

# --- SendInput constants ---------------------------------------------------
_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_VK_RETURN = 0x0D
_VK_BACK = 0x08
_VK_CONTROL = 0x11
_VK_V = 0x56

# --- Clipboard constants ---------------------------------------------------
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
# Restore the prior clipboard this long after Ctrl+V, giving the target app time
# to read the paste before we put the old contents back.
_PASTE_SETTLE_S = 0.12

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


def _backspaces(n: int) -> list:
    """Build ``n`` Backspace key-down/key-up INPUT events."""
    events: list = []
    for _ in range(max(0, n)):
        events.append(_key_event(_VK_BACK, 0, 0))
        events.append(_key_event(_VK_BACK, 0, _KEYEVENTF_KEYUP))
    return events


def _replace_last_inputs(old_len: int, new_text: str) -> list:
    """Events to erase ``old_len`` chars then type ``new_text``.

    Pure/testable: backspaces are counted by code points (matching how the user
    perceives characters), then the replacement is typed via the normal path.
    """
    return _backspaces(old_len) + _text_to_inputs(new_text)


def _ctrl_v_inputs() -> list:
    """Key events for a single Ctrl+V chord (paste)."""
    return [
        _key_event(_VK_CONTROL, 0, 0),
        _key_event(_VK_V, 0, 0),
        _key_event(_VK_V, 0, _KEYEVENTF_KEYUP),
        _key_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP),
    ]


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

    #: Supported injection methods.
    METHODS = ("paste", "sendinput")

    def __init__(self, method: str = "paste"):
        """Args:
            method: ``"paste"`` (clipboard + Ctrl+V, default and most robust) or
                ``"sendinput"`` (per-character synthesized keystrokes — useful
                where paste isn't honored, e.g. some terminals). Unknown values
                fall back to ``"paste"``.
        """
        self.set_method(method)
        self.available = sys.platform == "win32"
        self._user32 = None
        self._kernel32 = None
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
            self._bind_clipboard()
        except Exception as e:  # pragma: no cover - Windows-only path
            logger.error("Could not bind user32.SendInput: %s", e)
            self.available = False

    def _bind_clipboard(self) -> None:  # pragma: no cover - Windows-only path
        """Bind the Win32 clipboard calls with 64-bit-safe signatures.

        Handle/pointer-returning calls MUST declare a pointer-sized restype, or
        ctypes defaults to a 32-bit c_int and truncates the handle — a classic
        source of clipboard corruption on 64-bit Windows.
        """
        u32 = self._user32
        k32 = self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        k32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
        k32.GlobalAlloc.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = (ctypes.c_void_p,)
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
        k32.GlobalUnlock.restype = wintypes.BOOL
        k32.GlobalFree.argtypes = (ctypes.c_void_p,)
        k32.GlobalFree.restype = ctypes.c_void_p

        u32.OpenClipboard.argtypes = (wintypes.HWND,)
        u32.OpenClipboard.restype = wintypes.BOOL
        u32.CloseClipboard.restype = wintypes.BOOL
        u32.EmptyClipboard.restype = wintypes.BOOL
        u32.IsClipboardFormatAvailable.argtypes = (wintypes.UINT,)
        u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        u32.GetClipboardData.argtypes = (wintypes.UINT,)
        u32.GetClipboardData.restype = ctypes.c_void_p
        u32.SetClipboardData.argtypes = (wintypes.UINT, ctypes.c_void_p)
        u32.SetClipboardData.restype = ctypes.c_void_p

    def inject(self, text: str) -> bool:
        """Insert ``text`` into whatever window currently has keyboard focus.

        Pastes via the clipboard (single Ctrl+V); falls back to per-character
        SendInput only if the clipboard can't be set.

        Returns:
            True if the text was delivered, False otherwise (empty text, not on
            Windows, or the input was blocked).
        """
        if not text or not self.available:
            return False
        if self.method == "sendinput":
            return self._send(_text_to_inputs(text))
        return self._paste(text)

    def replace_last(self, old_len: int, new_text: str) -> bool:
        """Erase the last ``old_len`` characters, then insert ``new_text``.

        Used by "correct that": backspace over the previously injected text in
        the focused field and paste the correction. Assumes focus is unchanged
        and the cursor sits at the end of that text — the caller is responsible
        for that precondition. No-op (returns False) off Windows.

        Backspaces are a short synthetic sequence (reliable); the replacement
        text goes in via the same clipboard paste as ``inject``.
        """
        if not self.available or old_len < 0:
            return False
        if old_len:
            self._send(_backspaces(old_len))
        if not new_text:
            return True
        if self.method == "sendinput":
            return self._send(_text_to_inputs(new_text))
        return self._paste(new_text)

    def set_method(self, method: str) -> str:
        """Select the injection method; unknown values fall back to ``paste``.

        Returns the method actually set, so a caller (tray/settings toggle) can
        reflect the effective value.
        """
        self.method = method if method in self.METHODS else "paste"
        if method not in self.METHODS:
            logger.warning("Unknown inject method %r; using 'paste'", method)
        return self.method

    # --- clipboard paste --------------------------------------------------

    def _paste(self, text: str) -> bool:
        """Set the clipboard to ``text``, send Ctrl+V, then restore the clipboard.

        Deliberately does NOT fall back to per-character SendInput. On systems
        where a keyboard hook mangles synthesized keystrokes, that fallback
        silently emits corrupted text ("I checked" -> "I eeecked") — far worse
        than injecting nothing. Callers who want the keystroke path must opt in
        with ``method="sendinput"``.
        """
        saved = self._get_clipboard_text()
        if not self._set_clipboard_text(text):
            logger.error(
                "Could not take the clipboard; skipping injection of %d chars. "
                "Another app may be holding it. Set inject_method='sendinput' to "
                "type instead of paste.", len(text),
            )
            return False
        ok = self._send(_ctrl_v_inputs())
        # Let the target consume the paste before restoring the prior clipboard.
        time.sleep(_PASTE_SETTLE_S)
        if saved is not None:
            self._set_clipboard_text(saved)
        return ok

    def _open_clipboard(self) -> bool:  # pragma: no cover - Windows-only path
        """Open the clipboard, retrying briefly if another app holds it."""
        for _ in range(10):
            if self._user32.OpenClipboard(0):
                return True
            time.sleep(0.01)
        logger.warning("Could not open clipboard (held by another app)")
        return False

    def _set_clipboard_text(self, text: str) -> bool:  # pragma: no cover - Win-only
        """Place ``text`` on the clipboard as CF_UNICODETEXT. Returns success."""
        if not self._open_clipboard():
            return False
        try:
            self._user32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            handle = self._kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
            if not handle:
                return False
            ptr = self._kernel32.GlobalLock(handle)
            if not ptr:
                self._kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(ptr, data, len(data))
            self._kernel32.GlobalUnlock(handle)
            # On success the system owns the handle — do not free it. On failure
            # we must, or the moveable block leaks.
            if not self._user32.SetClipboardData(_CF_UNICODETEXT, handle):
                self._kernel32.GlobalFree(handle)
                return False
            return True
        finally:
            self._user32.CloseClipboard()

    def _get_clipboard_text(self) -> Optional[str]:  # pragma: no cover - Win-only
        """Return the current clipboard text (CF_UNICODETEXT), or None."""
        if not self._user32.IsClipboardFormatAvailable(_CF_UNICODETEXT):
            return None
        if not self._open_clipboard():
            return None
        try:
            handle = self._user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                return None
            ptr = self._kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                self._kernel32.GlobalUnlock(handle)
        finally:
            self._user32.CloseClipboard()

    def _send(self, events: list) -> bool:
        """Deliver a list of INPUT events via SendInput. Returns success."""
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
