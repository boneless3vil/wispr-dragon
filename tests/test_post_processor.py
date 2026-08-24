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


# --- spoken capitalization commands ---------------------------------------
# The command is consumed and re-cases the word that follows it. The engine
# may auto-punctuate between command and target ("No caps, 26").

def test_all_caps_next_word(processor):
    result = processor.process("all caps tomorrow is fine", apply_formatting=True)
    assert "TOMORROW" in result
    assert "caps" not in result.lower()


def test_no_caps_next_word(processor):
    result = processor.process("say it no caps Tomorrow", apply_formatting=True)
    assert "tomorrow" in result
    assert "Tomorrow" not in result
    assert "caps" not in result.lower()


def test_no_caps_survives_engine_comma(processor):
    # Engine auto-punctuates: "No caps, hello"
    result = processor.process("No caps, hello there", apply_formatting=True)
    assert result.startswith("hello")


def test_cap_next_word(processor):
    result = processor.process("cap police force", apply_formatting=True)
    assert "Police force" in result
    assert "cap " not in result.lower()


def test_caps_on_off_span(processor):
    result = processor.process("caps on the quick brown fox caps off ran away",
                               apply_formatting=True)
    assert "The Quick Brown Fox" in result
    assert "ran away" in result


def test_caps_on_without_off_runs_to_end(processor):
    result = processor.process("caps on meeting notes for monday",
                               apply_formatting=True)
    assert "Meeting Notes For Monday" in result


def test_no_caps_command_skipped_without_formatting(processor):
    result = processor.process("no caps Tomorrow", apply_formatting=False)
    assert "no caps Tomorrow" == result


def test_no_caps_on_off_span(processor):
    result = processor.process(
        "no caps on This Is All Lower no caps off But Not This",
        apply_formatting=True)
    assert "this is all lower" in result
    assert "But Not This" in result


def test_no_caps_on_without_off_runs_to_end(processor):
    result = processor.process("no caps on Keep It All Down",
                               apply_formatting=True)
    assert "keep it all down" in result


def test_no_caps_on_survives_engine_comma(processor):
    # Engine auto-punctuates: "No caps on, Hello There"
    result = processor.process("No caps on, Hello There", apply_formatting=True)
    assert "hello there" in result


def test_all_caps_on_off_span(processor):
    result = processor.process(
        "all caps on shouting now all caps off but not here",
        apply_formatting=True)
    assert "SHOUTING NOW" in result
    assert "but not here" in result


def test_caps_on_still_title_cases(processor):
    # Bare "caps on" must not be shadowed by the longer span commands.
    result = processor.process("caps on the quick fox caps off done",
                               apply_formatting=True)
    assert "The Quick Fox" in result
    assert "done" in result
