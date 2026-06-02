"""Tests for client-side correction command parsing (pure)."""

from __future__ import annotations

from wispr_dragon.client.correction_commands import (
    is_correct_trigger,
    parse_selection,
)


# --- trigger --------------------------------------------------------------

def test_trigger_correct_that():
    assert is_correct_trigger("correct that") is True
    assert is_correct_trigger("Correct that.") is True
    assert is_correct_trigger("correct this") is True


def test_trigger_negatives():
    assert is_correct_trigger("correct the spelling") is False
    assert is_correct_trigger("that is correct") is False
    assert is_correct_trigger("hello world") is False
    assert is_correct_trigger("") is False


# --- selection grammar ----------------------------------------------------

def test_choose_numeric():
    assert parse_selection("choose 2") == {"action": "choose", "index": 2}


def test_choose_word():
    assert parse_selection("choose two") == {"action": "choose", "index": 2}
    assert parse_selection("pick three") == {"action": "choose", "index": 3}


def test_bare_number():
    assert parse_selection("two") == {"action": "choose", "index": 2}
    assert parse_selection("3") == {"action": "choose", "index": 3}


def test_cancel():
    assert parse_selection("cancel") == {"action": "cancel"}
    assert parse_selection("never mind") == {"action": "cancel"}


def test_freehand_returns_none():
    assert parse_selection("hello world") is None
    assert parse_selection("choose elephant") is None
    assert parse_selection("") is None
