"""Tests for command mode matching."""

import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from wispr_dragon.modes.command_mode import match_command, load_commands


@pytest.fixture(autouse=True)
def setup_commands():
    # Load from the default commands file
    builtin = Path(__file__).parent.parent / "data" / "default_commands.yaml"
    if builtin.exists():
        load_commands(user_path=Path("/dev/null"))


def test_exact_match():
    result = match_command("scratch that")
    assert result is not None
    assert result["action"] == "undo_last"


def test_exact_match_case_insensitive():
    result = match_command("Scratch That")
    assert result is not None
    assert result["action"] == "undo_last"


def test_select_all():
    result = match_command("select all")
    assert result is not None
    assert result["action"] == "keystroke"


def test_no_match():
    result = match_command("random gibberish that matches nothing", threshold=95)
    assert result is None


def test_fuzzy_match():
    result = match_command("scatch that", threshold=75)
    assert result is not None
    assert result["action"] == "undo_last"
