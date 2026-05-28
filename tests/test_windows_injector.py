"""Tests for the Windows SendInput text injector.

The SendInput call itself only works on native Windows, so off Windows the
injector is inert. What *is* portable — and verified here — is the event
construction (``_text_to_inputs``) and the no-op / empty-input behavior. The
ctypes structures are plain memory layouts, so they build fine on any OS.
"""

import sys

from wispr_dragon.client.windows_injector import (
    INPUT,
    WindowsTextInjector,
    _text_to_inputs,
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


def test_inject_empty_text_returns_false():
    assert WindowsTextInjector().inject("") is False


def test_inject_is_a_safe_noop_off_windows():
    if sys.platform == "win32":
        return  # this test asserts the non-Windows fallback
    # Must not raise, and must report that nothing was injected.
    assert WindowsTextInjector().inject("hello world") is False
