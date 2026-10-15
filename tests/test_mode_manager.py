"""Tests for ModeManager always-on command matching, sleep gating,
dictation-only enforcement, and the undo buffer (modes/mode_manager.py).

Pure logic: no audio, no Qt.
"""

from types import SimpleNamespace

import pytest

from wispr_dragon.modes.mode_manager import Mode, ModeManager
from wispr_dragon.modes.orchestrator import DictationOrchestrator
from wispr_dragon.modes.transforms import build_transformers


class FakePostProcessor:
    def process(self, text, apply_formatting=True):
        return text


def _recording_manager(**kwargs):
    """ModeManager with every handler recording (action, text)."""
    mm = ModeManager(**kwargs)
    fired = []
    mm.register_handler("undo_last", lambda text: fired.append(("undo_last", text)))
    for action in ("open_correction_window", "keystroke", "macro"):
        mm.register_handler(
            action, lambda text, args=None, _a=action: fired.append((_a, text))
        )
    return mm, fired


# --- Always-on commands must match the WHOLE utterance --------------------

@pytest.mark.parametrize("sentence", [
    "Go to sleep early tonight.",
    "Scratch that itch.",
    "Correct that's what I said.",
    "Start numbers are low.",
    "Wake up call at seven.",
    "Switch to command mode later, please.",
])
def test_always_on_does_not_fire_inside_ordinary_sentences(sentence):
    mm, fired = _recording_manager()
    out = mm.process_text(sentence)
    assert out == sentence  # dictated verbatim
    assert mm.mode == Mode.DICTATION
    assert fired == []


@pytest.mark.parametrize("utterance,expected_mode", [
    ("Go to sleep.", Mode.SLEEP),
    ("go to sleep", Mode.SLEEP),
    ("Start spelling!", Mode.SPELLING),
    ("  Numbers   mode. ", Mode.NUMBERS),
    ("Switch to command mode.", Mode.COMMAND),
])
def test_always_on_tolerates_punctuation_and_whitespace(utterance, expected_mode):
    mm, _ = _recording_manager()
    assert mm.process_text(utterance) is None
    assert mm.mode == expected_mode


def test_scratch_that_with_trailing_period_fires_undo():
    mm, fired = _recording_manager()
    mm.record_output("hello")
    assert mm.process_text("Scratch that.") is None
    assert fired == [("undo_last", "hello")]


# --- Sleep mode honours only "wake up" -------------------------------------

@pytest.mark.parametrize("utterance", [
    "scratch that",
    "correct that",
    "switch to command mode",
    "switch to dictation mode",
    "start spelling",
    "numbers mode",
    "hello world",
])
def test_sleep_mode_ignores_everything_but_wake(utterance):
    mm, fired = _recording_manager()
    mm.record_output("something")
    mm.process_text("go to sleep")
    assert mm.mode == Mode.SLEEP
    assert mm.process_text(utterance) is None
    assert mm.mode == Mode.SLEEP
    assert fired == []


def test_wake_up_leaves_sleep():
    mm, _ = _recording_manager()
    mm.process_text("go to sleep")
    assert mm.process_text("Wake up.") is None
    assert mm.mode == Mode.DICTATION


# --- Dictation-only enforcement ----------------------------------------------

def test_dictation_only_blocks_switch_to_command_mode():
    mm, fired = _recording_manager(dictation_only=True)
    assert mm.process_text("switch to command mode") is None
    assert mm.mode == Mode.DICTATION
    assert fired == []


def test_dictation_only_blocks_keystroke_and_macro_actions():
    mm, fired = _recording_manager(dictation_only=True)
    mm._mode = Mode.COMMAND  # simulate: can't be reached legitimately
    mm._execute_action("keystroke", "select all", {"keys": "ctrl+a"})
    mm._execute_action("macro", "open browser", {"macro": {"action": "launch"}})
    assert fired == []


def test_dictation_only_still_allows_dictation_features():
    mm, fired = _recording_manager(dictation_only=True)
    mm.record_output("abc")
    mm.process_text("scratch that")
    mm.process_text("correct that")
    mm.process_text("start numbers")
    assert mm.mode == Mode.NUMBERS
    assert [a for a, _ in fired] == ["undo_last", "open_correction_window"]


def test_dictation_only_derived_from_macro_runner_security_policy():
    runner = SimpleNamespace(
        security=SimpleNamespace(is_dictation_only=lambda: True),
        find_macro=lambda text: None,
    )
    mm, _ = _recording_manager(macro_runner=runner)
    assert mm.process_text("switch to command mode") is None
    assert mm.mode == Mode.DICTATION


def test_non_bool_security_answer_is_not_treated_as_dictation_only():
    # A mock/stub returning a truthy non-bool must not lock the user out.
    runner = SimpleNamespace(
        security=SimpleNamespace(is_dictation_only=lambda: "yes"),
        find_macro=lambda text: None,
    )
    mm, _ = _recording_manager(macro_runner=runner)
    mm.process_text("switch to command mode")
    assert mm.mode == Mode.COMMAND


# --- Undo buffer records the final emitted text ------------------------------

def test_process_text_does_not_record_undo():
    mm, fired = _recording_manager()
    assert mm.process_text("hello") == "hello"
    mm.process_text("scratch that")
    assert fired == []  # nothing recorded -> nothing to undo


def test_undo_receives_transformed_numbers_text():
    mm, fired = _recording_manager()
    orch = DictationOrchestrator(FakePostProcessor(), mm, transformers=build_transformers())
    orch.handle_transcript("start numbers")
    out = orch.handle_transcript("forty two")
    assert out.text == "42"
    orch.handle_transcript("scratch that")
    assert fired == [("undo_last", "42")]


def test_undo_receives_transformed_spelling_text():
    mm, fired = _recording_manager()
    orch = DictationOrchestrator(FakePostProcessor(), mm, transformers=build_transformers())
    orch.handle_transcript("start spelling")
    orch.handle_transcript("cap a b c")
    orch.handle_transcript("scratch that")
    assert fired == [("undo_last", "Abc")]


def test_caller_can_record_exactly_what_it_injected():
    """Headless path: the orchestrator doesn't record; the caller records the
    injected text (including the separator space) so undo length matches."""
    mm, fired = _recording_manager()
    orch = DictationOrchestrator(
        FakePostProcessor(), mm, transformers=build_transformers(), record_outputs=False
    )
    orch.handle_transcript("start numbers")
    out = orch.handle_transcript("forty two")
    mm.record_output(out.text + " ")
    orch.handle_transcript("scratch that")
    assert fired == [("undo_last", "42 ")]


def test_undo_buffer_is_bounded():
    mm, fired = _recording_manager()
    for i in range(30):
        mm.record_output(f"t{i}")
    for _ in range(30):
        mm.process_text("scratch that")
    assert len(fired) == 20
    assert fired[0] == ("undo_last", "t29")


def test_record_output_ignores_blank_text():
    mm, fired = _recording_manager()
    mm.record_output("")
    mm.record_output("   ")
    mm.process_text("scratch that")
    assert fired == []
