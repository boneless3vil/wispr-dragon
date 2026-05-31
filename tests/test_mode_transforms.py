"""Tests for Spelling/Numbers mode transforms and their orchestrator wiring.

Pure logic — no audio, no Qt.
"""

import pytest

from wispr_dragon.modes.mode_manager import Mode, ModeManager
from wispr_dragon.modes.orchestrator import DictationOrchestrator
from wispr_dragon.modes.transforms import (
    NumbersTransformer,
    SpellingTransformer,
    build_transformers,
)


# --- Spelling -------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("alpha bravo charlie", "abc"),
    ("a b c", "abc"),
    ("cap a b c", "Abc"),
    ("cap h i", "Hi"),
    ("h e l l o", "hello"),
    ("one two three", "123"),
    ("a period", "a."),
    ("capital w", "W"),
])
def test_spelling_transform(text, expected):
    assert SpellingTransformer().transform(text) == expected


def test_spelling_empty_unchanged():
    assert SpellingTransformer().transform("") == ""


# --- Numbers --------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("zero", "0"),
    ("nineteen", "19"),
    ("forty two", "42"),
    ("one hundred", "100"),
    ("one hundred twenty three", "123"),
    ("two thousand", "2000"),
    ("three point five", "3.5"),
    ("three point one four", "3.14"),
    ("ten dollars", "$10"),
])
def test_numbers_transform(text, expected):
    assert NumbersTransformer().transform(text) == expected


def test_numbers_passthrough_when_not_numeric():
    # Non-number phrases are left untouched rather than guessed at.
    assert NumbersTransformer().transform("hello world") == "hello world"


# --- Orchestrator integration --------------------------------------------

class FakePostProcessor:
    def process(self, text, apply_formatting=True):
        return text


def _make():
    mm = ModeManager()
    orch = DictationOrchestrator(FakePostProcessor(), mm, transformers=build_transformers())
    return mm, orch


def test_spelling_mode_transforms_dictation():
    mm, orch = _make()
    assert orch.handle_transcript("start spelling").consumed
    assert mm.mode == Mode.SPELLING
    out = orch.handle_transcript("alpha bravo")
    assert out.text == "ab"


def test_numbers_mode_transforms_dictation():
    mm, orch = _make()
    assert orch.handle_transcript("numbers mode").consumed
    assert mm.mode == Mode.NUMBERS
    out = orch.handle_transcript("forty two")
    assert out.text == "42"


def test_stop_spelling_returns_to_dictation():
    mm, orch = _make()
    orch.handle_transcript("start spelling")
    assert orch.handle_transcript("stop spelling").consumed
    assert mm.mode == Mode.DICTATION
    # Back in dictation, no transform is applied.
    out = orch.handle_transcript("hello there")
    assert out.text == "hello there"
