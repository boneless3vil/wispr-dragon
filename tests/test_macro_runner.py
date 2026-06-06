"""Tests for macro execution system."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from wispr_dragon.macros.macro_runner import MacroRunner


@pytest.fixture
def temp_user_dir():
    """Create temporary user directory with macro/script structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        user_dir = Path(tmpdir)
        (user_dir / "macros").mkdir()
        (user_dir / "scripts").mkdir()
        (user_dir / "config.yaml").write_text("security:\n  allow_python_scripts: true\n")
        yield user_dir


@pytest.fixture
def mock_text_injector():
    """Create mock text injector."""
    return MagicMock()


@pytest.fixture
def macro_runner(temp_user_dir, mock_text_injector):
    """Create MacroRunner instance with temp directory."""
    return MacroRunner(temp_user_dir, mock_text_injector)


def test_macro_runner_init(temp_user_dir):
    """Test MacroRunner initialization."""
    runner = MacroRunner(temp_user_dir)
    assert runner.user_dir == temp_user_dir
    assert runner.macros_dir == temp_user_dir / "macros"
    assert runner.scripts_dir == temp_user_dir / "scripts"


def test_load_macros_single_file(macro_runner, temp_user_dir):
    """Test loading macros from YAML file."""
    macros_file = temp_user_dir / "macros" / "test.yaml"
    macros_file.write_text(
        yaml.dump({
            "macros": [
                {"trigger": "open browser", "action": "launch", "program": "firefox"},
                {"trigger": "close window", "action": "keystroke", "keys": "alt+F4"},
            ]
        })
    )

    macro_runner.reload_macros()
    assert len(macro_runner._macros_cache) == 2
    assert "open browser" in macro_runner._macros_cache
    assert "close window" in macro_runner._macros_cache


def test_load_macros_multiple_files(macro_runner, temp_user_dir):
    """Test loading macros from multiple YAML files."""
    (temp_user_dir / "macros" / "file1.yaml").write_text(
        yaml.dump({"macros": [{"trigger": "macro1", "action": "text", "content": "hello"}]})
    )
    (temp_user_dir / "macros" / "file2.yaml").write_text(
        yaml.dump({"macros": [{"trigger": "macro2", "action": "text", "content": "world"}]})
    )

    macro_runner.reload_macros()
    assert len(macro_runner._macros_cache) == 2
    assert "macro1" in macro_runner._macros_cache
    assert "macro2" in macro_runner._macros_cache


def test_find_macro_exact_match(macro_runner, temp_user_dir):
    """Test finding macro with exact text match."""
    macro_runner._macros_cache = {
        "open browser": {"action": "launch", "program": "firefox"},
    }

    result = macro_runner.find_macro("open browser")
    assert result is not None
    assert result["action"] == "launch"
    assert result["program"] == "firefox"


def test_find_macro_case_insensitive(macro_runner):
    """Test that macro matching is case-insensitive."""
    macro_runner._macros_cache = {
        "open browser": {"action": "launch", "program": "firefox"},
    }

    result = macro_runner.find_macro("Open Browser")
    assert result is not None


def test_find_macro_with_placeholder(macro_runner):
    """Test finding macro with placeholder extraction."""
    macro_runner._macros_cache = {
        "open {app}": {"action": "launch", "program": "{app}"},
    }

    result = macro_runner.find_macro("open firefox")
    assert result is not None
    assert result["_captured_args"]["app"] == "firefox"


def test_find_macro_not_found(macro_runner):
    """Test that find_macro returns None for non-matching text."""
    macro_runner._macros_cache = {
        "open browser": {"action": "launch", "program": "firefox"},
    }

    result = macro_runner.find_macro("random gibberish")
    assert result is None


def test_execute_keystroke_valid(macro_runner):
    """Test executing valid keystroke macro."""
    macro = {"action": "keystroke", "keys": "ctrl+c"}

    with patch("subprocess.run") as mock_run:
        result = macro_runner.execute(macro)
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "xdotool" in args
        assert "ctrl+c" in args


def test_execute_keystroke_invalid_pattern(macro_runner):
    """Test that keystroke with shell metacharacters is rejected."""
    macro = {"action": "keystroke", "keys": "$(rm -rf /)"}

    result = macro_runner.execute(macro)
    assert result is False


def test_execute_keystroke_missing_keys(macro_runner):
    """Test keystroke without 'keys' field."""
    macro = {"action": "keystroke"}

    result = macro_runner.execute(macro)
    assert result is False


def test_execute_text(macro_runner, mock_text_injector):
    """Test executing text injection macro."""
    macro = {"action": "text", "content": "hello world"}

    result = macro_runner.execute(macro)
    assert result is True
    mock_text_injector.inject.assert_called_once_with("hello world")


def test_execute_text_missing_content(macro_runner):
    """Test text macro without 'content' field."""
    macro = {"action": "text"}

    result = macro_runner.execute(macro)
    assert result is False


def test_execute_text_no_injector(temp_user_dir):
    """Test text macro when text_injector is not configured."""
    runner = MacroRunner(temp_user_dir, text_injector=None)
    macro = {"action": "text", "content": "hello"}

    result = runner.execute(macro)
    assert result is False


@patch("shutil.which")
def test_execute_launch_valid(mock_which, macro_runner):
    """Test executing program launch macro."""
    mock_which.return_value = "/usr/bin/firefox"

    macro = {"action": "launch", "program": "firefox"}

    with patch("subprocess.Popen") as mock_popen:
        result = macro_runner.execute(macro)
        assert result is True
        mock_popen.assert_called_once()


@patch("shutil.which")
def test_execute_launch_program_not_found(mock_which, macro_runner):
    """Test launching non-existent program."""
    mock_which.return_value = None

    macro = {"action": "launch", "program": "nonexistent"}

    result = macro_runner.execute(macro)
    assert result is False


def test_execute_launch_disabled_by_policy(macro_runner, temp_user_dir):
    """Test that program launch is blocked when disabled by security policy."""
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  allow_program_launch: false\n"
    )
    macro_runner.security._config_cache = None  # Clear cache

    macro = {"action": "launch", "program": "firefox"}

    result = macro_runner.execute(macro)
    assert result is False


@patch("shutil.which")
def test_execute_launch_with_placeholder(mock_which, macro_runner):
    """Test program launch with placeholder substitution."""
    mock_which.return_value = "/usr/bin/firefox"

    macro = {"action": "launch", "program": "{app}"}
    captured_args = {"app": "firefox"}

    with patch("subprocess.Popen"):
        result = macro_runner.execute(macro, captured_args)
        assert result is True


def test_execute_python_script_disabled(macro_runner, temp_user_dir):
    """Test that Python scripts are blocked when disabled by policy."""
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  allow_python_scripts: false\n"
    )
    macro_runner.security._config_cache = None  # Clear cache

    macro = {"action": "python_script", "script": "test.py"}

    result = macro_runner.execute(macro)
    assert result is False


def test_execute_unknown_action(macro_runner):
    """Test executing macro with unknown action."""
    macro = {"action": "unknown_action"}

    result = macro_runner.execute(macro)
    assert result is False


def test_execute_no_action(macro_runner):
    """Test executing macro without action field."""
    macro = {}

    result = macro_runner.execute(macro)
    assert result is False


def test_execute_dictation_only_mode(macro_runner, temp_user_dir):
    """Test that macros are blocked in dictation-only mode."""
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  dictation_only: true\n"
    )
    macro_runner.security._config_cache = None  # Clear cache

    macro = {"action": "keystroke", "keys": "ctrl+c"}

    result = macro_runner.execute(macro)
    assert result is False


def test_placeholder_substitution(macro_runner):
    """Test placeholder substitution in text."""
    result = macro_runner._substitute_placeholders(
        "Hello {name}, welcome to {place}",
        {"name": "Alice", "place": "Wonderland"}
    )
    assert result == "Hello Alice, welcome to Wonderland"


def test_keystroke_timeout(macro_runner):
    """Test keystroke execution with timeout."""
    macro = {"action": "keystroke", "keys": "ctrl+c"}

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = Exception("Command timed out")
        result = macro_runner.execute(macro)
        assert result is False
