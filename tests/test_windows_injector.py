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
    _backspaces,
    _ctrl_v_inputs,
    _replace_last_inputs,
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
