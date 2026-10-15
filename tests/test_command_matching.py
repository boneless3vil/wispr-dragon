"""Tests for command mode matching and registry."""

from pathlib import Path

import pytest

from wispr_dragon.modes.command_mode import (
    match_command, load_commands, CommandRegistry
)


@pytest.fixture(autouse=True)
def setup_commands():
    """Load from the default commands file."""
    builtin = Path(__file__).parent.parent / "wispr_dragon" / "data" / "default_commands.yaml"
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
        builtin = Path(__file__).parent.parent / "wispr_dragon" / "data" / "default_commands.yaml"
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
        builtin = Path(__file__).parent.parent / "wispr_dragon" / "data" / "default_commands.yaml"
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


# --- Packaging: built-ins ship inside the package ----------------------------

from wispr_dragon.modes import command_mode  # noqa: E402


def test_builtin_commands_live_inside_the_package():
    import wispr_dragon

    pkg_dir = Path(wispr_dragon.__file__).resolve().parent
    builtin = command_mode.builtin_commands_path()
    assert builtin.is_file()
    assert Path(str(builtin)).resolve().is_relative_to(pkg_dir)
    assert (pkg_dir / "data" / "default_macros.yaml").is_file()


def test_registry_loads_builtins_without_user_file(tmp_path):
    registry = CommandRegistry(user_dir=tmp_path)  # no commands.yaml there
    registry.load()
    triggers = {c["trigger"] for c in registry.commands}
    assert {"scratch that", "select all"} <= triggers


def test_registry_user_dir_commands(tmp_path):
    (tmp_path / "commands.yaml").write_text(
        "commands:\n  - trigger: shout\n    action: keystroke\n    keys: F5\n"
    )
    registry = CommandRegistry(user_dir=tmp_path)
    result = registry.match("shout")
    assert result is not None and result["args"]["keys"] == "F5"


def test_registry_does_not_reload_when_legitimately_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(command_mode, "builtin_commands_path", lambda: tmp_path / "missing.yaml")
    registry = CommandRegistry(user_dir=tmp_path)
    calls = []
    real_load = registry.load
    monkeypatch.setattr(registry, "load", lambda *a, **k: (calls.append(1), real_load(*a, **k)))
    registry.match("anything")
    registry.match("anything else")
    assert registry.commands == []
    assert len(calls) == 1


# --- Trigger normalisation / placeholder patterns -----------------------------

class TestTriggerMatching:

    @pytest.fixture
    def registry(self):
        return CommandRegistry()

    def test_trailing_punctuation_exact_match(self, registry):
        registry.commands = [{"trigger": "select all", "action": "keystroke", "keys": "ctrl+a"}]
        result = registry.match("Select all.")
        assert result is not None and result["action"] == "keystroke"

    def test_exact_beats_placeholder_with_punctuation(self, registry):
        registry.commands = [
            {"trigger": "open {app}", "action": "launch_any"},
            {"trigger": "open browser", "action": "launch_browser"},
        ]
        assert registry.match("Open browser.")["action"] == "launch_browser"

    def test_placeholder_capture_strips_punctuation(self, registry):
        registry.commands = [{"trigger": "correct {word}", "action": "replace"}]
        result = registry.match("Correct hello.")
        assert result["args"]["word"] == "hello"

    def test_placeholder_is_anchored(self, registry):
        registry.commands = [{"trigger": "correct {word}", "action": "replace"}]
        assert registry.match("please correct hello", threshold=101) is None

    @pytest.mark.parametrize("bad", ["open {app", "open app}", "{a} {a}", "go {1x}"])
    def test_invalid_placeholder_trigger_skipped(self, registry, bad):
        registry.commands = [
            {"trigger": bad, "action": "bad"},
            {"trigger": "correct {word}", "action": "replace"},
        ]
        # No re.error; the valid trigger still matches.
        assert registry.match("correct hello")["action"] == "replace"

    def test_placeholder_triggers_not_fuzzy_matched(self, registry):
        registry.commands = [{"trigger": "open {app}", "action": "launch"}]
        # "open app" is a near-literal of the raw trigger text; it must not
        # fuzzy-match and return a command with no captured args.
        result = registry.match("open {app", threshold=50)
        assert result is None or "app" in result["args"]


def test_shared_trigger_helper_is_used_by_both_matchers():
    from wispr_dragon.macros import macro_runner
    from wispr_dragon.modes import triggers

    assert command_mode.compile_trigger is triggers.compile_trigger
    assert macro_runner.compile_trigger is triggers.compile_trigger
