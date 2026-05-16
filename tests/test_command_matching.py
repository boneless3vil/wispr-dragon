"""Tests for command mode matching and registry."""

import tempfile
from pathlib import Path

import pytest

from wispr_dragon.modes.command_mode import (
    match_command, load_commands, CommandRegistry
)


@pytest.fixture(autouse=True)
def setup_commands():
    """Load from the default commands file."""
    builtin = Path(__file__).parent.parent / "data" / "default_commands.yaml"
    if builtin.exists():
        load_commands(user_path=Path("/dev/null"))


# Legacy API tests (backward compatibility)

def test_exact_match():
    """Test exact command match via legacy API."""
    result = match_command("scratch that")
    assert result is not None
    assert result["action"] == "undo_last"


def test_exact_match_case_insensitive():
    """Test case-insensitive matching via legacy API."""
    result = match_command("Scratch That")
    assert result is not None
    assert result["action"] == "undo_last"


def test_select_all():
    """Test select all command via legacy API."""
    result = match_command("select all")
    assert result is not None
    assert result["action"] == "keystroke"


def test_no_match():
    """Test no match returns None via legacy API."""
    result = match_command("random gibberish that matches nothing", threshold=95)
    assert result is None


def test_fuzzy_match():
    """Test fuzzy matching via legacy API."""
    result = match_command("scatch that", threshold=75)
    assert result is not None
    assert result["action"] == "undo_last"


# CommandRegistry class tests

class TestCommandRegistry:
    """Tests for CommandRegistry class."""

    @pytest.fixture
    def registry(self):
        """Create a fresh registry for each test."""
        return CommandRegistry()

    def test_registry_initialization(self, registry):
        """Test CommandRegistry initializes with empty commands."""
        assert registry.commands == []

    def test_registry_load_builtin_commands(self, registry):
        """Test loading built-in commands."""
        builtin = Path(__file__).parent.parent / "data" / "default_commands.yaml"
        if builtin.exists():
            registry.load(user_path=Path("/dev/null"))
            assert len(registry.commands) > 0

    def test_registry_load_user_commands(self, registry, tmp_path):
        """Test loading user commands from file."""
        user_file = tmp_path / "commands.yaml"
        user_file.write_text(
            "commands:\n"
            "  - trigger: custom command\n"
            "    action: text\n"
            "    content: hello\n"
        )

        registry.load(user_path=user_file)
        # At minimum should have loaded the custom command
        assert any(cmd.get("trigger") == "custom command" for cmd in registry.commands)

    def test_registry_exact_match(self, registry):
        """Test exact matching in registry."""
        registry.commands = [
            {"trigger": "scratch that", "action": "undo_last", "description": "Undo"}
        ]

        result = registry.match("scratch that")
        assert result is not None
        assert result["action"] == "undo_last"

    def test_registry_exact_match_case_insensitive(self, registry):
        """Test case-insensitive exact matching."""
        registry.commands = [
            {"trigger": "scratch that", "action": "undo_last"}
        ]

        result = registry.match("SCRATCH THAT")
        assert result is not None

    def test_registry_placeholder_matching(self, registry):
        """Test placeholder extraction in matching."""
        registry.commands = [
            {"trigger": "correct {word}", "action": "replace"}
        ]

        result = registry.match("correct hello")
        assert result is not None
        assert "word" in result["args"]
        assert result["args"]["word"] == "hello"

    def test_registry_fuzzy_match(self, registry):
        """Test fuzzy matching."""
        registry.commands = [
            {"trigger": "scratch that", "action": "undo_last"}
        ]

        result = registry.match("scatch that", threshold=75)
        assert result is not None
        assert result["action"] == "undo_last"

    def test_registry_fuzzy_match_below_threshold(self, registry):
        """Test that fuzzy match below threshold returns None."""
        registry.commands = [
            {"trigger": "scratch that", "action": "undo_last"}
        ]

        result = registry.match("completely different text", threshold=95)
        assert result is None

    def test_registry_no_commands_auto_loads(self, registry):
        """Test that matching with empty registry auto-loads commands."""
        builtin = Path(__file__).parent.parent / "data" / "default_commands.yaml"
        if builtin.exists():
            registry.match("scratch that")
            assert len(registry.commands) > 0

    def test_registry_preserves_extra_fields(self, registry):
        """Test that non-structural fields are preserved in args."""
        registry.commands = [
            {
                "trigger": "test",
                "action": "custom",
                "description": "A test",
                "param1": "value1",
                "param2": "value2",
            }
        ]

        result = registry.match("test")
        assert result["args"]["param1"] == "value1"
        assert result["args"]["param2"] == "value2"
        # trigger and action are structural, so they go in args too
        assert "description" in result

    def test_registry_multiple_commands(self, registry):
        """Test registry with multiple commands."""
        registry.commands = [
            {"trigger": "command one", "action": "action1"},
            {"trigger": "command two", "action": "action2"},
            {"trigger": "command three", "action": "action3"},
        ]

        for i in range(1, 4):
            result = registry.match(f"command {['one', 'two', 'three'][i-1]}")
            assert result is not None

    def test_registry_exact_match_takes_precedence(self, registry):
        """Test that exact match takes precedence over fuzzy."""
        registry.commands = [
            {"trigger": "scratch that", "action": "exact"},
            {"trigger": "scrath that", "action": "fuzzy"},
        ]

        result = registry.match("scratch that")
        assert result["action"] == "exact"

    def test_registry_placeholder_takes_precedence_over_fuzzy(self, registry):
        """Test that placeholder match takes precedence over fuzzy."""
        registry.commands = [
            {"trigger": "correct {word}", "action": "placeholder"},
            {"trigger": "something", "action": "fuzzy"},
        ]

        result = registry.match("correct hello", threshold=50)
        assert result["action"] == "placeholder"

    def test_registry_make_result_static_method(self, registry):
        """Test _make_result as static method."""
        cmd = {"trigger": "test", "action": "go", "extra": "data"}
        result = CommandRegistry._make_result(cmd)

        assert result["action"] == "go"
        assert result["args"]["extra"] == "data"
        # trigger, action, description are structural keys and not in args
        assert "trigger" not in result["args"]
        assert "action" not in result["args"]
