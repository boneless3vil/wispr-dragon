"""Tests for the Windows SendInput text injector.

The SendInput call itself only works on native Windows, so off Windows the
injector is inert. What *is* portable — and verified here — is the event
construction (``_text_to_inputs``) and the no-op / empty-input behavior. The
ctypes structures are plain memory layouts, so they build fine on any OS.
"""

import sys
import time

import pytest

from wispr_dragon.client.windows_injector import (
    DEFAULT_PASTE_SETTLE_MS,
    INPUT,
    WindowsTextInjector,
    _backspaces,
    _clipboard_text,
    _ctrl_v_inputs,
    _replace_last_inputs,
    _text_to_inputs,
    sanitize_text,
)


def test_each_bmp_char_makes_a_down_and_up_event():
    events = _text_to_inputs("abc")
    assert len(events) == 6  # 3 chars x (key-down + key-up)
    assert all(isinstance(e, INPUT) for e in events)


def test_empty_text_makes_no_events():
    assert _text_to_inputs("") == []


def test_newline_becomes_a_return_keypress():
    # 'a' (2 events) + '\n' -> Return (2) + 'b' (2)
    assert len(_text_to_inputs("a\nb")) == 6
    # a CR/LF pair collapses to two Return keypresses (4 events)
    assert len(_text_to_inputs("\r\n")) == 4


def test_astral_char_emits_a_surrogate_pair():
    # U+1F600 is two UTF-16 code units -> 2 down + 2 up
    assert len(_text_to_inputs("\U0001F600")) == 4


def test_bmp_accented_char_is_a_single_unit():
    # é is in the BMP — one code unit, unlike an astral character.
    assert len(_text_to_inputs("café")) == 8  # 4 chars


def test_injector_constructs_on_any_platform():
    injector = WindowsTextInjector()
    assert injector.available == (sys.platform == "win32")


# --- injection method selection ------------------------------------------

def test_ctrl_v_inputs_is_a_four_event_chord():
    # ctrl down, v down, v up, ctrl up
    assert len(_ctrl_v_inputs()) == 4
    assert all(isinstance(e, INPUT) for e in _ctrl_v_inputs())


def test_default_method_is_paste():
    assert WindowsTextInjector().method == "paste"


def test_method_can_be_set_to_sendinput():
    assert WindowsTextInjector(method="sendinput").method == "sendinput"


def test_unknown_method_falls_back_to_paste():
    assert WindowsTextInjector(method="nonsense").method == "paste"


def test_set_method_switches_and_returns_effective():
    inj = WindowsTextInjector()
    assert inj.set_method("sendinput") == "sendinput"
    assert inj.method == "sendinput"
    assert inj.set_method("bogus") == "paste"  # invalid -> paste


def test_inject_empty_text_returns_false():
    assert WindowsTextInjector().inject("") is False


def test_inject_is_a_safe_noop_off_windows():
    if sys.platform == "win32":
        return  # this test asserts the non-Windows fallback
    # Must not raise, and must report that nothing was injected.
    assert WindowsTextInjector().inject("hello world") is False


# --- replace_last (correction) -------------------------------------------

def test_backspaces_count():
    assert len(_backspaces(3)) == 6  # 3 x (down + up)
    assert _backspaces(0) == []
    assert _backspaces(-1) == []


def test_replace_last_inputs_backspaces_then_types():
    # erase 4 chars (8 events) + type "hi" (4 events)
    events = _replace_last_inputs(4, "hi")
    assert len(events) == 8 + 4
    assert all(isinstance(e, INPUT) for e in events)


def test_replace_last_noop_off_windows():
    if sys.platform == "win32":
        return
    assert WindowsTextInjector().replace_last(5, "fixed") is False


def test_replace_last_rejects_negative_len():
    assert WindowsTextInjector().replace_last(-1, "x") is False


# --- text sanitizing --------------------------------------------------------

def test_sanitize_strips_c0_controls_but_keeps_newline_and_tab():
    assert sanitize_text("a\x1bb\x08c\x00d") == "abcd"
    assert sanitize_text("line\nnext\tcol") == "line\nnext\tcol"


def test_sanitize_collapses_crlf_and_drops_lone_cr():
    assert sanitize_text("a\r\nb") == "a\nb"
    assert sanitize_text("a\rb") == "ab"


def test_sanitize_keeps_unicode():
    assert sanitize_text("café — \U0001F600") == "café — \U0001F600"
    assert sanitize_text("") == ""


def test_clipboard_text_uses_crlf():
    assert _clipboard_text("a\nb\n") == "a\r\nb\r\n"


# --- paste settle delay -----------------------------------------------------

def test_paste_settle_defaults_to_250ms():
    assert DEFAULT_PASTE_SETTLE_MS == 250
    assert WindowsTextInjector().paste_settle_s == 0.25


def test_paste_settle_is_configurable_and_validated():
    assert WindowsTextInjector(paste_settle_ms=400).paste_settle_s == 0.4
    assert WindowsTextInjector(paste_settle_ms="300").paste_settle_s == 0.3
    assert WindowsTextInjector(paste_settle_ms="junk").paste_settle_s == 0.25
    assert WindowsTextInjector(paste_settle_ms=-5).paste_settle_s == 0.0
    assert WindowsTextInjector(paste_settle_ms=10**9).paste_settle_s == 2.0


# --- clipboard restore logic (fake clipboard; runs on every OS) --------------

class _FakeClipboard:
    """Stands in for the Win32 clipboard on an injector instance."""

    def __init__(self, injector, initial="previous"):
        self.text = initial
        self.seq = 100
        self.writes = []
        self.private = []  # privacy-format flag of each write
        injector.paste_settle_s = 0
        injector._get_clipboard_text = lambda: self.text
        injector._set_clipboard_text = self.write
        injector._clipboard_sequence = lambda: self.seq
        injector._send = lambda events: True

    def write(self, text, private=False):
        self.text = text
        self.seq += 1
        self.writes.append(text)
        self.private.append(private)
        return True


class _FakeScheduler:
    """Collects scheduled callbacks instead of running them (like call_later)."""

    def __init__(self):
        self.calls = []

    def __call__(self, delay, callback):
        handle = _Handle(callback)
        self.calls.append((delay, handle))
        return handle

    def fire_pending(self):
        for _, handle in self.calls:
            if not handle.cancelled:
                handle.callback()


class _Handle:
    def __init__(self, callback):
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


def test_paste_restores_the_previous_clipboard():
    inj = WindowsTextInjector()
    cb = _FakeClipboard(inj)
    assert inj._paste("hello") is True
    assert cb.writes == ["hello", "previous"]
    assert cb.text == "previous"


def test_paste_does_not_clobber_a_copy_made_during_the_settle_window():
    inj = WindowsTextInjector()
    cb = _FakeClipboard(inj)

    def send_while_user_copies(events):
        cb.write("user copied this")  # bumps the sequence number
        return True

    inj._send = send_while_user_copies
    inj._paste("hello")
    assert cb.text == "user copied this"
    assert cb.writes == ["hello", "user copied this"]


def test_paste_puts_crlf_text_on_the_clipboard():
    inj = WindowsTextInjector()
    cb = _FakeClipboard(inj, initial=None)
    inj._paste("one\ntwo")
    assert cb.writes == ["one\r\ntwo"]  # nothing to restore


def test_inject_sanitizes_before_pasting():
    inj = WindowsTextInjector()
    cb = _FakeClipboard(inj)
    inj.available = True  # exercise the logic off Windows too
    assert inj.inject("a\x1b[2Jb\r\n") is True
    assert cb.writes[0] == "a[2Jb\r\n"


def test_inject_of_only_control_chars_is_a_noop():
    inj = WindowsTextInjector()
    cb = _FakeClipboard(inj)
    inj.available = True
    assert inj.inject("\x07\x1b") is False
    assert cb.writes == []


def test_privacy_formats_only_on_dictation_not_on_restore():
    inj = WindowsTextInjector()
    cb = _FakeClipboard(inj)
    inj._paste("dictated")
    assert cb.writes == ["dictated", "previous"]
    assert cb.private == [True, False], "the user's own text is restored as-is"


def test_restore_is_scheduled_not_blocking():
    """The settle wait must not block the caller's event loop (audio capture)."""
    sched = _FakeScheduler()
    inj = WindowsTextInjector(paste_settle_ms=250, scheduler=sched)
    cb = _FakeClipboard(inj)
    inj.paste_settle_s = 0.25
    t0 = time.monotonic()
    assert inj._paste("hello") is True
    assert time.monotonic() - t0 < 0.1, "paste returned only after the settle delay"
    assert cb.text == "hello", "restore must wait for the settle delay"
    assert [d for d, _ in sched.calls] == [0.25]
    sched.fire_pending()
    assert cb.text == "previous"


def test_back_to_back_pastes_restore_the_original_clipboard():
    """A second paste before the first restore must not snapshot (and later
    restore) the first dictation as if it were the user's clipboard."""
    sched = _FakeScheduler()
    inj = WindowsTextInjector(scheduler=sched)
    cb = _FakeClipboard(inj)
    inj._paste("first")
    inj._paste("second")
    assert sched.calls[0][1].cancelled, "the superseded restore is cancelled"
    sched.fire_pending()
    assert cb.text == "previous"
    assert cb.writes == ["first", "second", "previous"]


def test_copy_between_pastes_becomes_the_clipboard_to_restore():
    sched = _FakeScheduler()
    inj = WindowsTextInjector(scheduler=sched)
    cb = _FakeClipboard(inj)
    inj._paste("first")
    sched.fire_pending()           # restored "previous"
    cb.write("user copy")          # user copies something new
    inj._paste("second")
    sched.fire_pending()
    assert cb.text == "user copy"


def test_no_text_clipboard_is_not_replaced_by_a_later_restore():
    """Clipboard held no text: the dictation stays, and a following paste
    must not later 'restore' that earlier dictation."""
    sched = _FakeScheduler()
    inj = WindowsTextInjector(scheduler=sched)
    cb = _FakeClipboard(inj, initial=None)
    inj._paste("first")
    sched.fire_pending()
    inj._paste("second")
    sched.fire_pending()
    assert cb.writes == ["first", "second"]


def test_flush_restore_runs_a_pending_restore_now():
    sched = _FakeScheduler()
    inj = WindowsTextInjector(scheduler=sched)
    cb = _FakeClipboard(inj)
    inj._paste("hello")
    inj.flush_restore()
    assert cb.text == "previous"
    assert sched.calls[0][1].cancelled


def test_scheduler_without_a_loop_falls_back_to_inline_restore():
    inj = WindowsTextInjector(scheduler=lambda delay, cb: None)
    cb = _FakeClipboard(inj)
    inj._paste("hello")
    assert cb.text == "previous"


# --- real Win32 clipboard (Windows only) --------------------------------------

def _clipboard_snapshot_or_skip(inj):
    """Text currently on the clipboard; skip when the clipboard can't be opened
    (headless / sandboxed session) or holds non-text data we'd destroy."""
    import ctypes
    from ctypes import wintypes

    u32 = inj._user32
    u32.EnumClipboardFormats.argtypes = (wintypes.UINT,)
    u32.EnumClipboardFormats.restype = wintypes.UINT
    if not u32.OpenClipboard(0):
        pytest.skip(f"clipboard not accessible here (WinError {ctypes.get_last_error()})")
    try:
        formats, fmt = [], 0
        while True:
            fmt = u32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            formats.append(fmt)
    finally:
        u32.CloseClipboard()
    # CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT, CF_LOCALE + our own markers. Anything
    # else (bitmaps, files, HTML / RTF, app-private data) would be lost.
    textual = {1, 7, 13, 16} | set(inj._private_format_ids())
    if any(f not in textual for f in formats):
        pytest.skip("clipboard holds non-text data; not touching it")
    return inj._get_clipboard_text()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 clipboard")
def test_real_clipboard_round_trip_sets_privacy_formats():
    inj = WindowsTextInjector()
    saved = _clipboard_snapshot_or_skip(inj)
    u32 = inj._user32
    history, cloud = inj._private_format_ids()
    exclude_all = u32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
    try:
        assert inj._set_clipboard_text("wispr test\r\nline 2", private=True)
        assert inj._get_clipboard_text() == "wispr test\r\nline 2"
        assert u32.IsClipboardFormatAvailable(history)
        assert u32.IsClipboardFormatAvailable(cloud)
        assert not u32.IsClipboardFormatAvailable(exclude_all), (
            "must stay visible to RDP / VM clipboard redirection"
        )
        assert inj._set_clipboard_text("restored", private=False)
        assert not u32.IsClipboardFormatAvailable(history)
    finally:
        if saved is not None:
            inj._set_clipboard_text(saved, private=False)
        elif u32.OpenClipboard(0):
            u32.EmptyClipboard()
            u32.CloseClipboard()
