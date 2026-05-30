"""Tests for the shared DictationOrchestrator (modes/orchestrator.py).

Pure logic — no audio, no Qt. Exercises the post-process -> mode/command
dispatch -> transform pipeline that both the headless loop and the floating
dictation box route finalized transcript segments through.
"""

from wispr_dragon.modes.mode_manager import Mode, ModeManager
from wispr_dragon.modes.orchestrator import DictationOrchestrator


class FakePostProcessor:
    """Records calls; returns text unchanged so assertions are exact."""

    def __init__(self):
        self.calls = []

    def process(self, text, apply_formatting=True):
        self.calls.append((text, apply_formatting))
        return text


class UpperTransformer:
    def transform(self, text):
        return text.upper()


def _make(transformers=None):
    pp = FakePostProcessor()
    mm = ModeManager()
    orch = DictationOrchestrator(pp, mm, transformers=transformers)
    return pp, mm, orch


def test_plain_dictation_returns_text():
    _, _, orch = _make()
    out = orch.handle_transcript("hello world")
    assert out.has_text
    assert out.text == "hello world"
    assert not out.consumed


def test_empty_input_is_consumed():
    pp, _, orch = _make()
    out = orch.handle_transcript("   ")
    assert out.consumed
    assert not out.has_text
    assert pp.calls == []  # short-circuits before post-processing


def test_scratch_that_invokes_undo_handler_and_is_consumed():
    _, mm, orch = _make()
    undone = []
    mm.register_handler("undo_last", lambda text: undone.append(text))
    orch.handle_transcript("first phrase")  # populate the undo buffer
    out = orch.handle_transcript("scratch that")
    assert out.consumed
    assert undone == ["first phrase"]


def test_correction_command_dispatches_handler():
    _, mm, orch = _make()
    corrected = []
    mm.register_handler("open_correction_window", lambda text, args=None: corrected.append(text))
    out = orch.handle_transcript("correct that")
    assert out.consumed
    assert corrected  # handler fired


def test_mode_switch_is_consumed_and_changes_mode():
    _, mm, orch = _make()
    out = orch.handle_transcript("switch to command mode")
    assert out.consumed
    assert mm.mode == Mode.COMMAND


def test_sleep_swallows_dictation_until_wake():
    _, mm, orch = _make()
    orch.handle_transcript("go to sleep")
    assert mm.mode == Mode.SLEEP
    out = orch.handle_transcript("this should be ignored")
    assert out.consumed
    assert not out.has_text
    wake = orch.handle_transcript("wake up")
    assert wake.consumed
    assert mm.mode == Mode.DICTATION


def test_formatting_enabled_only_in_dictation_mode():
    pp, _, orch = _make()
    orch.handle_transcript("hello")
    assert pp.calls[-1] == ("hello", True)

    orch.handle_transcript("switch to command mode")
    pp.calls.clear()
    orch.handle_transcript("unmatched command text")
    assert pp.calls[-1][1] is False  # no auto-formatting outside dictation


def test_transformer_applied_to_active_mode_output():
    _, _, orch = _make(transformers={Mode.DICTATION: UpperTransformer()})
    out = orch.handle_transcript("hello")
    assert out.text == "HELLO"
