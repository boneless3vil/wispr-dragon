"""Tests for the post-processing pipeline."""

import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

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
