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


# --- Security config wiring / YAML macro policy -------------------------------

from wispr_dragon.config import SecurityConfig  # noqa: E402


def test_in_memory_dictation_only_blocks_execute(temp_user_dir, mock_text_injector):
    """--dictation-only lives only in memory; MacroRunner must honour it."""
    runner = MacroRunner(
        temp_user_dir, mock_text_injector, security_cfg=SecurityConfig(dictation_only=True)
    )
    with patch("subprocess.run") as mock_run:
        assert runner.execute({"action": "keystroke", "keys": "ctrl+c"}) is False
        mock_run.assert_not_called()
    assert runner.execute({"action": "text", "content": "x"}) is False
    mock_text_injector.inject.assert_not_called()


def test_yaml_macros_disabled_loads_nothing(temp_user_dir):
    (temp_user_dir / "macros" / "m.yaml").write_text(
        yaml.dump({"macros": [{"trigger": "say hi", "action": "text", "content": "hi"}]})
    )
    runner = MacroRunner(temp_user_dir, security_cfg=SecurityConfig(allow_yaml_macros=False))
    assert runner._macros_cache == {}
    assert runner.find_macro("say hi") is None


def test_load_macros_accepts_bare_list_file(macro_runner, temp_user_dir):
    """The macro editor saves ``[macro]`` (a bare list) — the runner must load it."""
    (temp_user_dir / "macros" / "say_hi.yaml").write_text(
        yaml.dump([{"trigger": "say hi", "action": "text", "content": "hi"}])
    )
    macro_runner.reload_macros()
    assert macro_runner.find_macro("say hi") is not None


def test_load_macros_ignores_malformed_entries(macro_runner, temp_user_dir):
    (temp_user_dir / "macros" / "junk.yaml").write_text(
        yaml.dump({"macros": ["not a dict", {"trigger": 5}, {"trigger": "ok", "action": "text"}]})
    )
    (temp_user_dir / "macros" / "scalar.yaml").write_text("just a string\n")
    macro_runner.reload_macros()
    assert list(macro_runner._macros_cache) == ["ok"]


# --- Trigger matching: punctuation, anchoring, bad patterns --------------------

def test_find_macro_trailing_punctuation_prefers_exact(macro_runner):
    macro_runner._macros_cache = {
        "open browser": {"trigger": "open browser", "action": "launch", "program": "firefox"},
        "open {app}": {"trigger": "open {app}", "action": "launch", "program": "{app}"},
    }
    result = macro_runner.find_macro("Open browser.")
    assert result is not None
    assert result["program"] == "firefox"
    assert "_captured_args" not in result


def test_find_macro_placeholder_strips_trailing_punctuation(macro_runner):
    macro_runner._macros_cache = {
        "open {app}": {"trigger": "open {app}", "action": "launch", "program": "{app}"},
    }
    result = macro_runner.find_macro("Open Firefox!")
    assert result["_captured_args"] == {"app": "firefox"}


def test_find_macro_placeholder_is_anchored(macro_runner):
    macro_runner._macros_cache = {
        "open {app}": {"trigger": "open {app}", "action": "launch", "program": "{app}"},
    }
    assert macro_runner.find_macro("please open firefox") is None
    assert macro_runner.find_macro("open firefox; rm -rf") is None


@pytest.mark.parametrize("bad_trigger", ["open {app", "open app}", "{a} and {a}", "run {1x}"])
def test_invalid_placeholder_trigger_is_skipped(temp_user_dir, bad_trigger):
    (temp_user_dir / "macros" / "bad.yaml").write_text(
        yaml.dump({"macros": [
            {"trigger": bad_trigger, "action": "text", "content": "x"},
            {"trigger": "say {word}", "action": "text", "content": "y"},
        ]})
    )
    runner = MacroRunner(temp_user_dir)
    # Must not raise re.error at match time; the good macro still works.
    assert runner.find_macro("open firefox") is None
    assert runner.find_macro("say hello")["_captured_args"] == {"word": "hello"}


# --- Python script macros: path containment + hash-pinned execution ----------

@pytest.mark.parametrize("script", ["../evil.py", "../../x.py", "sub/x.py", "/tmp/x.py"])
def test_python_script_rejects_non_bare_names(macro_runner, script):
    with patch.object(macro_runner.script_runner, "run_script") as run, \
            patch("subprocess.run") as sp:
        assert macro_runner.execute({"action": "python_script", "script": script}) is False
        run.assert_not_called()
        sp.assert_not_called()


def test_script_runner_rejects_non_bare_names(macro_runner):
    with patch("subprocess.run") as sp:
        assert macro_runner.script_runner.run_script("../evil.py") is None
        sp.assert_not_called()


def _sign(runner, name, source):
    path = runner.scripts_dir / name
    path.write_bytes(source)
    assert runner.security.sign_script(path)
    return path


def test_script_runner_executes_the_verified_bytes(macro_runner):
    """The verified bytes are piped to the interpreter (no hash-then-reopen race)."""
    source = b"print('signed')\n"
    _sign(macro_runner, "s.py", source)

    completed = MagicMock(returncode=0, stdout=b"signed\n", stderr=b"")
    with patch("subprocess.run", return_value=completed) as sp:
        out = macro_runner.script_runner.run_script("s.py")
    assert out == "signed\n"
    argv = sp.call_args[0][0]
    kwargs = sp.call_args[1]
    assert argv[-1] == "-"
    assert "-I" in argv
    assert not any("s.py" in str(a) for a in argv)  # never re-opened by path
    assert kwargs["input"] == source
    assert kwargs["timeout"] == 30


def test_script_runner_refuses_modified_script(macro_runner):
    path = _sign(macro_runner, "s.py", b"print('signed')\n")
    path.write_bytes(b"print('tampered')\n")
    with patch("subprocess.run") as sp:
        assert macro_runner.script_runner.run_script("s.py") is None
        sp.assert_not_called()


def test_script_runner_real_run_with_minimal_env(macro_runner, monkeypatch):
    monkeypatch.setenv("WISPR_TEST_SECRET", "leak-me")
    _sign(
        macro_runner,
        "env.py",
        b"import os\nprint('secret' if 'WISPR_TEST_SECRET' in os.environ else 'clean')\n",
    )
    assert macro_runner.script_runner.run_script("env.py").strip() == "clean"
