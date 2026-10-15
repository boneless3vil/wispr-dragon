"""Tests for main.py CLI handling: admin lock / signing, CLI override
validation, --print-key, and the headless pipeline wiring.

No audio, no model load: anything that would start the engine is stubbed to
raise, and Config's default path is redirected so the real
~/.wispr_dragon/config.yaml is never touched.
"""

import json
import sys
from unittest.mock import MagicMock

import pytest
import yaml

import wispr_dragon.config as config_mod
import wispr_dragon.main as main_mod
from wispr_dragon.config import Config, SecurityConfig
from wispr_dragon.macros.security import SecurityPolicy
from wispr_dragon.modes import command_mode
from wispr_dragon.modes.mode_manager import Mode


class _EngineStarted(Exception):
    pass


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Never write the real default config; never load a model."""
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", tmp_path / "default-config.yaml")

    def _no_engine(*a, **k):
        raise _EngineStarted()

    monkeypatch.setattr(main_mod, "create_engine", _no_engine)
    monkeypatch.setattr(main_mod, "_detect_lan_ip", lambda: "10.0.0.5")
    # Fresh global command registry so user_dir changes don't leak.
    monkeypatch.setattr(command_mode, "_registry", command_mode.CommandRegistry())


@pytest.fixture
def user_dir(tmp_path):
    d = tmp_path / "userdir"
    (d / "scripts").mkdir(parents=True)
    (d / "macros").mkdir()
    return d


def _write_config(tmp_path, user_dir, **security):
    path = tmp_path / "custom-config.yaml"
    data = {"user_dir": str(user_dir)}
    if security:
        data["security"] = security
    path.write_text(yaml.safe_dump(data))
    return path


def _run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["wispr_dragon", *argv])
    return main_mod.main()


def _answers(monkeypatch, *answers):
    """Feed getpass prompts in order; fail loudly on an unexpected prompt."""
    it = iter(answers)

    def fake_getpass(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"unexpected password prompt: {prompt!r}")

    monkeypatch.setattr(main_mod.getpass, "getpass", fake_getpass)


def _lock(user_dir, password, policy=None):
    import bcrypt

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
    assert SecurityPolicy(user_dir).set_admin_lock(pw_hash, policy or {})


# --- Item 12: --print-key -------------------------------------------------------

def test_print_key_without_server_is_an_error(monkeypatch, tmp_path, user_dir):
    cfg = _write_config(tmp_path, user_dir)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, "--print-key", "--config", str(cfg))
    assert exc.value.code == 2


def test_print_key_saves_generated_key_to_the_given_config(monkeypatch, tmp_path, user_dir, capsys):
    cfg = _write_config(tmp_path, user_dir)
    assert _run_main(monkeypatch, "--server", "--print-key", "--config", str(cfg)) == 0
    saved = yaml.safe_load(cfg.read_text())
    assert saved["server"]["api_key"]
    assert saved["server"]["api_key"] in capsys.readouterr().out
    assert not (tmp_path / "default-config.yaml").exists()


# --- Item 13: validated CLI overrides ---------------------------------------------

@pytest.mark.parametrize("flags", [
    ["--beam-size", "0"],
    ["--beam-size", "-3"],
    ["--device", "tpu"],
])
def test_invalid_engine_override_is_an_argparse_error(monkeypatch, tmp_path, user_dir, flags):
    cfg = _write_config(tmp_path, user_dir)
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, *flags, "--security-status", "--config", str(cfg))
    assert exc.value.code == 2


def test_valid_engine_overrides_are_applied():
    parser = MagicMock()
    args = MagicMock(model="medium.en", device="cpu", compute_type="int8", beam_size=3,
                     dictation_only=True)
    config = Config()
    main_mod._apply_cli_overrides(parser, args, config)
    parser.error.assert_not_called()
    assert config.engine.model_size == "medium.en"
    assert config.engine.device == "cpu"
    assert config.engine.compute_type == "int8"
    assert config.engine.beam_size == 3
    assert config.security.dictation_only is True


# --- Item 1: --dictation-only / --config reach the security policy ----------------

def test_security_status_reflects_cli_and_custom_config(monkeypatch, tmp_path, user_dir, capsys):
    cfg = _write_config(tmp_path, user_dir, allow_program_launch=False)
    assert _run_main(monkeypatch, "--security-status", "--dictation-only", "--config", str(cfg)) == 0
    out = capsys.readouterr().out
    assert "Dictation-only mode:     True" in out
    assert "Allow program launch:    False" in out


# --- Item 2: admin lock snapshots (never loosens) the effective policy -----------

def test_admin_lock_snapshots_current_policy(monkeypatch, tmp_path, user_dir):
    cfg = _write_config(tmp_path, user_dir, allow_python_scripts=False, dictation_only=True)
    _answers(monkeypatch, "pw", "pw")
    assert _run_main(monkeypatch, "--admin-lock", "--config", str(cfg)) == 0
    lock = json.loads((user_dir / "security.lock").read_text())
    assert lock["policy"] == {
        "allow_python_scripts": False,
        "allow_yaml_macros": True,
        "allow_program_launch": True,
        "dictation_only": True,
    }


def test_relock_requires_current_password(monkeypatch, tmp_path, user_dir):
    cfg = _write_config(tmp_path, user_dir)
    _lock(user_dir, "old", {"allow_python_scripts": False})
    before = (user_dir / "security.lock").read_text()

    _answers(monkeypatch, "wrong")
    assert _run_main(monkeypatch, "--admin-lock", "--config", str(cfg)) == 1
    assert (user_dir / "security.lock").read_text() == before

    _answers(monkeypatch, "old", "new", "new")
    assert _run_main(monkeypatch, "--admin-lock", "--config", str(cfg)) == 0
    policy = SecurityPolicy(user_dir)
    assert policy.verify_admin_password("new") is True
    # Re-locking keeps the previous lock's restriction (effective policy).
    assert policy.allows_python_scripts() is False


def test_sign_script_requires_admin_password_while_locked(monkeypatch, tmp_path, user_dir):
    cfg = _write_config(tmp_path, user_dir)
    (user_dir / "scripts" / "s.py").write_text("print('x')\n")
    manifest = user_dir / "scripts" / ".manifest.json"
    _lock(user_dir, "pw")

    _answers(monkeypatch, "wrong")
    assert _run_main(monkeypatch, "--sign-script", "s.py", "--config", str(cfg)) == 1
    assert not manifest.exists()

    _answers(monkeypatch, "pw")
    assert _run_main(monkeypatch, "--sign-script", "s.py", "--config", str(cfg)) == 0
    assert "s.py" in json.loads(manifest.read_text())


def test_sign_script_unlocked_needs_no_password(monkeypatch, tmp_path, user_dir):
    cfg = _write_config(tmp_path, user_dir)
    (user_dir / "scripts" / "s.py").write_text("print('x')\n")
    _answers(monkeypatch)  # any prompt fails the test
    assert _run_main(monkeypatch, "--sign-script", "s.py", "--config", str(cfg)) == 0


@pytest.mark.parametrize("name", ["../s.py", "sub/s.py", "/tmp/s.py"])
def test_sign_script_rejects_paths(monkeypatch, tmp_path, user_dir, name):
    cfg = _write_config(tmp_path, user_dir)
    _answers(monkeypatch)
    assert _run_main(monkeypatch, "--sign-script", name, "--config", str(cfg)) == 1
    assert not (user_dir / "scripts" / ".manifest.json").exists()


# --- Items 8 / 11 / 1: headless pipeline wiring -----------------------------------

class _FakePostProcessor:
    def process(self, text, apply_formatting=True):
        return text


def _headless(user_dir, **security):
    config = Config()
    config.user_dir = user_dir
    config.security = SecurityConfig(**security)
    injector = MagicMock()
    mode_mgr, orchestrator = main_mod._build_headless_pipeline(
        config, _FakePostProcessor(), injector
    )
    return injector, mode_mgr, orchestrator


def _say(orchestrator, mode_mgr, injector, text):
    outcome = orchestrator.handle_transcript(text)
    main_mod._emit_headless(outcome, injector, mode_mgr)
    return outcome


def test_headless_undo_removes_exactly_what_was_injected(user_dir):
    injector, mm, orch = _headless(user_dir)
    _say(orch, mm, injector, "start numbers")
    _say(orch, mm, injector, "forty two")
    injector.inject.assert_called_once_with("42 ")
    _say(orch, mm, injector, "scratch that")
    injector.undo.assert_called_once_with("42 ")
    # Only one entry was recorded: a second undo has nothing to remove.
    _say(orch, mm, injector, "scratch that")
    injector.undo.assert_called_once()


def test_headless_correct_that_does_not_open_qt_dialog(user_dir, monkeypatch, caplog):
    import wispr_dragon.ui.correction_window as cw

    window_cls = MagicMock()
    monkeypatch.setattr(cw, "CorrectionWindow", window_cls)
    injector, mm, orch = _headless(user_dir)
    _say(orch, mm, injector, "hello")
    with caplog.at_level("INFO"):
        outcome = _say(orch, mm, injector, "correct that")
    assert outcome.consumed
    window_cls.assert_not_called()
    assert "headless" in caplog.text.lower()


def test_headless_dictation_only_blocks_command_mode(user_dir):
    injector, mm, orch = _headless(user_dir, dictation_only=True)
    _say(orch, mm, injector, "switch to command mode")
    assert mm.mode == Mode.DICTATION
