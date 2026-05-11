"""Tests for the user dictionary."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from wispr_dragon.correction.dictionary import UserDictionary


@pytest.fixture
def tmp_dict(tmp_path):
    path = tmp_path / "test_dict.json"
    return UserDictionary(path=path)


def test_add_correction(tmp_dict):
    tmp_dict.add_correction("john ball win", "John Baldwin")
    assert tmp_dict.get_correction("john ball win") == "John Baldwin"


def test_correction_frequency(tmp_dict):
    tmp_dict.add_correction("john ball win", "John Baldwin")
    tmp_dict.add_correction("john ball win", "John Baldwin")
    tmp_dict.add_correction("john ball win", "John Baldwin")
    high = tmp_dict.get_high_confidence_corrections(threshold=3)
    assert "john ball win" in high
    assert high["john ball win"] == "John Baldwin"


def test_remove_correction(tmp_dict):
    tmp_dict.add_correction("test", "Test")
    assert tmp_dict.remove_correction("test")
    assert tmp_dict.get_correction("test") is None


def test_custom_words(tmp_dict):
    tmp_dict.add_custom_word("ROCm")
    tmp_dict.add_custom_word("Wispr-Dragon")
    assert "ROCm" in tmp_dict.custom_words
    assert "Wispr-Dragon" in tmp_dict.custom_words


def test_hotwords(tmp_dict):
    tmp_dict.add_correction("john ball win", "John Baldwin")
    tmp_dict.add_custom_word("ROCm")
    hotwords = tmp_dict.build_hotwords()
    assert "John Baldwin" in hotwords
    assert "ROCm" in hotwords


def test_initial_prompt(tmp_dict):
    tmp_dict.add_custom_word("Jonathan")
    tmp_dict.add_custom_word("Baldwin")
    prompt = tmp_dict.build_initial_prompt()
    assert "Jonathan" in prompt
    assert "Baldwin" in prompt


def test_persistence(tmp_path):
    path = tmp_path / "persist.json"
    d1 = UserDictionary(path=path)
    d1.add_correction("wrong", "Right")
    d1.add_custom_word("TestWord")

    d2 = UserDictionary(path=path)
    assert d2.get_correction("wrong") == "Right"
    assert "TestWord" in d2.custom_words


def test_phrase_replacement(tmp_dict):
    tmp_dict.add_phrase_replacement("per say", "per se")
    assert tmp_dict.phrase_replacements["per say"] == "per se"
