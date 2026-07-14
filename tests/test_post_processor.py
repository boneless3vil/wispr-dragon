"""Tests for the post-processing pipeline."""


import pytest

from wispr_dragon.correction.dictionary import UserDictionary
from wispr_dragon.correction.post_processor import PostProcessor


@pytest.fixture
def processor(tmp_path):
    path = tmp_path / "test_dict.json"
    dictionary = UserDictionary(path=path)
    # Add some corrections
    for _ in range(3):
        dictionary.add_correction("john ball win", "John Baldwin")
    dictionary.add_custom_word("Jonathan")
    dictionary.add_phrase_replacement("per say", "per se")
    return PostProcessor(dictionary, fuzzy_threshold=85, auto_apply_threshold=3)


def test_exact_correction(processor):
    result = processor.process("john ball win said hello", apply_formatting=False)
    assert "John Baldwin" in result


def test_formatting_period(processor):
    result = processor.process("hello period how are you", apply_formatting=True)
    assert "hello." in result or "hello ." in result


def test_formatting_comma(processor):
    result = processor.process("hello comma world", apply_formatting=True)
    assert "hello," in result


def test_formatting_new_paragraph(processor):
    result = processor.process("first paragraph new paragraph second paragraph", apply_formatting=True)
    assert "\n\n" in result


def test_phrase_replacement(processor):
    result = processor.process("it is not per say correct", apply_formatting=False)
    assert "per se" in result


def test_capitalization(processor):
    result = processor.process("i talked to jonathan", apply_formatting=False)
    assert "Jonathan" in result


# --- adjacent-punctuation collapse ---------------------------------------
# When you say "comma"/"period" the engine also auto-punctuates from your
# pauses, so the spoken mark collides with the model's own ("Hello,, world.,,").

def test_doubled_comma_collapses(processor):
    # Engine already put a comma in; the spoken "comma" adds another.
    result = processor.process("hello, comma world", apply_formatting=True)
    assert ",," not in result
    assert "hello," in result


def test_comma_then_period_keeps_period(processor):
    # "one., this" -> the stronger sentence-ender wins.
    result = processor.process("this is one period comma this is two", apply_formatting=True)
    assert ".," not in result and ",." not in result
    assert "one." in result


def test_ellipsis_survives_collapse(processor):
    result = processor.process("wait ellipsis really", apply_formatting=True)
    assert "..." in result


def test_repeated_period_collapses(processor):
    result = processor.process("done period period", apply_formatting=True)
    assert ".." not in result.replace("...", "")  # ignore any legit ellipsis
    assert "done." in result
