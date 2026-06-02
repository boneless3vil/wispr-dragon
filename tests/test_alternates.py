"""Tests for synthesized correction alternates (pure, no Qt)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from wispr_dragon.correction.alternates import (
    homophones_for,
    synthesize_alternates,
)
from wispr_dragon.correction.dictionary import UserDictionary


@pytest.fixture
def dictionary():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield UserDictionary(path=Path(tmpdir) / "dict.json")


# --- homophones -----------------------------------------------------------

def test_homophones_basic():
    assert set(homophones_for("their")) == {"there", "they're"}


def test_homophones_capitalization_mirrored():
    assert homophones_for("There") == ["Their", "They're"]


def test_homophones_unknown_word():
    assert homophones_for("kubernetes") == []


# --- synthesize_alternates ------------------------------------------------

def test_original_always_present_and_last_when_no_sources():
    alts = synthesize_alternates("zxqw", dictionary=None)
    assert alts == ["zxqw"]


def test_engine_alternatives_rank_first():
    alts = synthesize_alternates(
        "there", engine_alternatives=["their"], dictionary=None
    )
    assert alts[0] == "their"
    assert "there" in alts


def test_learned_correction_included(dictionary):
    dictionary.add_correction("kubernetis", "Kubernetes")
    alts = synthesize_alternates("kubernetis", dictionary=dictionary)
    assert "Kubernetes" in alts


def test_homophones_surface_for_common_word(dictionary):
    alts = synthesize_alternates("to", dictionary=dictionary)
    assert "too" in alts and "two" in alts
    assert alts[-1] == "to"  # original last


def test_fuzzy_neighbour_from_custom_words(dictionary):
    dictionary.add_custom_word("PostgreSQL")
    alts = synthesize_alternates("postgresql", dictionary=dictionary)
    assert "PostgreSQL" in alts


def test_no_duplicates_and_limit(dictionary):
    dictionary.add_correction("to", "too")  # also a homophone — must dedupe
    alts = synthesize_alternates("to", dictionary=dictionary, limit=4)
    assert len(alts) == len(set(alts))
    assert len(alts) <= 4


# --- dictionary .setdefault guard -----------------------------------------

def test_add_correction_survives_entry_without_alternatives(dictionary):
    # Simulate an externally-written entry missing the "alternatives" key.
    dictionary.corrections["foo"] = {"correct": "bar", "frequency": 1}
    # Must not KeyError.
    dictionary.add_correction("foo", "baz")
    assert dictionary.get_correction("foo") == "baz"
    assert "foo" in dictionary.corrections["foo"]["alternatives"]
