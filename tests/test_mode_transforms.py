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


@pytest.mark.parametrize("text,expected", [
    # Years / digit-group concatenation.
    ("twenty twenty", "2020"),
    ("nineteen ninety nine", "1999"),
    ("twenty ten", "2010"),
    ("nineteen hundred eighty four", "1984"),
    ("twenty one hundred", "2100"),
    # Digit strings (phone numbers, zip codes keep leading zeros).
    ("five five five one two one two", "5551212"),
    ("zero two one three nine", "02139"),
    # Ordinary compound numbers still add up.
    ("twenty five", "25"),
    ("one hundred five", "105"),
    ("one hundred and five", "105"),
    ("two thousand and five", "2005"),
    ("two thousand twenty", "2020"),
    ("two million three hundred thousand", "2300000"),
    # Fractions: oh/zero are digits; multi-word fractions keep every digit.
    ("three point oh five", "3.05"),
    ("three point zero five", "3.05"),
    ("three point fourteen", "3.14"),
    ("point five", "0.5"),
    ("ten point five dollars", "$10.5"),
])
def test_numbers_transform_regressions(text, expected):
    assert NumbersTransformer().transform(text) == expected


@pytest.mark.parametrize("text", [
    # No integer part and no fraction: nothing to convert.
    "dollars",
    "dollar",
    "point",
    "point dollars",
    # Whisper already produced digits: leave them alone.
    "10 dollars",
    "2 thousand",
    "$10",
    "3.14",
    # Unrecognised fraction tokens: don't guess, don't drop.
    "three point banana",
    "one point two point three",
    "and",
])
def test_numbers_transform_leaves_text_unchanged(text):
    assert NumbersTransformer().transform(text) == text


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
