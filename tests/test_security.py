"""Tests for security policy enforcement."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from wispr_dragon.macros.security import SecurityPolicy


@pytest.fixture
def temp_user_dir():
    """Create temporary user directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        user_dir = Path(tmpdir)
        (user_dir / "scripts").mkdir()
        (user_dir / "config.yaml").write_text("security:\n  allow_python_scripts: true\n")
        yield user_dir


@pytest.fixture
def security_policy(temp_user_dir):
    """Create SecurityPolicy instance with temp directory."""
    return SecurityPolicy(temp_user_dir)


def test_security_policy_init(temp_user_dir):
    """Test SecurityPolicy initialization."""
    policy = SecurityPolicy(temp_user_dir)
    assert policy.user_dir == temp_user_dir
    assert policy.config_file == temp_user_dir / "config.yaml"
    assert policy.lock_file == temp_user_dir / "security.lock"
    assert policy.scripts_dir == temp_user_dir / "scripts"
    assert policy.manifest_file == temp_user_dir / "scripts" / ".manifest.json"


def test_allows_python_scripts_default(security_policy):
    """Test that Python scripts are allowed by default."""
    assert security_policy.allows_python_scripts() is True


def test_allows_python_scripts_from_config(security_policy, temp_user_dir):
    """Test reading allow_python_scripts from config."""
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  allow_python_scripts: false\n"
    )
    security_policy._config_cache = None

    assert security_policy.allows_python_scripts() is False


def test_allows_yaml_macros_default(security_policy):
    """Test that YAML macros are allowed by default."""
    assert security_policy.allows_yaml_macros() is True


def test_allows_yaml_macros_from_config(security_policy, temp_user_dir):
    """Test reading allow_yaml_macros from config."""
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  allow_yaml_macros: false\n"
    )
    security_policy._config_cache = None

    assert security_policy.allows_yaml_macros() is False


def test_allows_program_launch_default(security_policy):
    """Test that program launch is allowed by default."""
    assert security_policy.allows_program_launch() is True


def test_allows_program_launch_from_config(security_policy, temp_user_dir):
    """Test reading allow_program_launch from config."""
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  allow_program_launch: false\n"
    )
    security_policy._config_cache = None

    assert security_policy.allows_program_launch() is False


def test_is_dictation_only_default(security_policy):
    """Test that dictation_only is False by default."""
    assert security_policy.is_dictation_only() is False


def test_is_dictation_only_from_config(security_policy, temp_user_dir):
    """Test reading dictation_only from config."""
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  dictation_only: true\n"
    )
    security_policy._config_cache = None

    assert security_policy.is_dictation_only() is True


def test_is_locked_when_no_lock_file(security_policy):
    """Test is_locked returns False when no lock file exists."""
    assert security_policy.is_locked() is False


def test_is_locked_when_lock_file_exists(security_policy, temp_user_dir):
    """Test is_locked returns True when lock file exists."""
    lock_data = {
        "password_hash": "bcrypt_hash_here",
        "policy": {"allow_python_scripts": False},
    }
    (temp_user_dir / "security.lock").write_text(json.dumps(lock_data))

    assert security_policy.is_locked() is True


def test_set_admin_lock(security_policy, temp_user_dir):
    """Test setting an admin lock."""
    policy = {
        "allow_python_scripts": False,
        "allow_yaml_macros": True,
        "allow_program_launch": True,
    }

    result = security_policy.set_admin_lock("bcrypt_hash", policy)
    assert result is True
    assert security_policy.lock_file.exists()

    # Verify lock file contents
    with open(security_policy.lock_file) as f:
        lock_data = json.load(f)
    assert lock_data["password_hash"] == "bcrypt_hash"
    assert lock_data["policy"] == policy


def test_admin_lock_overrides_config(security_policy, temp_user_dir):
    """Test that admin lock overrides config settings."""
    # Config allows python scripts
    (temp_user_dir / "config.yaml").write_text(
        "security:\n  allow_python_scripts: true\n"
    )

    # Lock disables python scripts
    policy = {"allow_python_scripts": False}
    security_policy.set_admin_lock("hash", policy)
    security_policy._config_cache = None

    # Lock should override config
    assert security_policy.allows_python_scripts() is False


def test_remove_admin_lock_success(security_policy, temp_user_dir):
    """Test removing admin lock with correct password hash."""
    password_hash = "bcrypt_hash_123"
    policy = {"allow_python_scripts": False}

    security_policy.set_admin_lock(password_hash, policy)
    assert security_policy.is_locked() is True

    result = security_policy.remove_admin_lock(password_hash)
    assert result is True
    assert security_policy.is_locked() is False


def test_remove_admin_lock_wrong_password(security_policy, temp_user_dir):
    """Test that remove_admin_lock fails with wrong password."""
    password_hash = "bcrypt_hash_123"
    policy = {"allow_python_scripts": False}

    security_policy.set_admin_lock(password_hash, policy)

    result = security_policy.remove_admin_lock("wrong_hash")
    assert result is False
    assert security_policy.is_locked() is True


def test_remove_admin_lock_no_lock_file(security_policy):
    """Test remove_admin_lock when no lock file exists."""
    result = security_policy.remove_admin_lock("any_hash")
    assert result is False


def test_sign_script(security_policy, temp_user_dir):
    """Test signing a script."""
    script_file = temp_user_dir / "scripts" / "test.py"
    script_file.write_text("print('hello')")

    result = security_policy.sign_script(script_file)
    assert result is True
    assert security_policy.manifest_file.exists()

    # Verify manifest
    with open(security_policy.manifest_file) as f:
        manifest = json.load(f)
    assert "test.py" in manifest
    assert len(manifest["test.py"]) == 64  # SHA-256 hex is 64 chars


def test_sign_nonexistent_script(security_policy, temp_user_dir):
    """Test signing a script that doesn't exist."""
    script_file = temp_user_dir / "scripts" / "nonexistent.py"

    result = security_policy.sign_script(script_file)
    assert result is False


def test_check_script_signature_valid(security_policy, temp_user_dir):
    """Test checking signature of a valid signed script."""
    script_file = temp_user_dir / "scripts" / "test.py"
    script_file.write_text("print('hello')")

    # Sign the script
    security_policy.sign_script(script_file)

    # Check signature
    result = security_policy.check_script_signature(script_file)
    assert result is True


def test_check_script_signature_unsigned(security_policy, temp_user_dir):
    """Test checking signature of an unsigned script."""
    script_file = temp_user_dir / "scripts" / "unsigned.py"
    script_file.write_text("print('unsigned')")

    result = security_policy.check_script_signature(script_file)
    assert result is False


def test_check_script_signature_modified(security_policy, temp_user_dir):
    """Test that modified script fails signature check."""
    script_file = temp_user_dir / "scripts" / "test.py"
    script_file.write_text("print('original')")

    # Sign the script
    security_policy.sign_script(script_file)

    # Modify the script
    script_file.write_text("print('modified')")

    # Signature check should fail
    result = security_policy.check_script_signature(script_file)
    assert result is False


def test_check_script_signature_nonexistent(security_policy, temp_user_dir):
    """Test checking signature of non-existent script."""
    script_file = temp_user_dir / "scripts" / "nonexistent.py"

    result = security_policy.check_script_signature(script_file)
    assert result is False


def test_hash_file_consistency(security_policy, temp_user_dir):
    """Test that hashing the same file produces the same hash."""
    script_file = temp_user_dir / "scripts" / "test.py"
    script_file.write_text("print('test')")

    hash1 = security_policy._hash_file(script_file)
    hash2 = security_policy._hash_file(script_file)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256


def test_hash_file_different_for_different_content(security_policy, temp_user_dir):
    """Test that different files produce different hashes."""
    file1 = temp_user_dir / "scripts" / "file1.py"
    file2 = temp_user_dir / "scripts" / "file2.py"
    file1.write_text("print('file1')")
    file2.write_text("print('file2')")

    hash1 = security_policy._hash_file(file1)
    hash2 = security_policy._hash_file(file2)

    assert hash1 != hash2


def test_load_manifest_empty_when_not_exists(security_policy):
    """Test that loading manifest returns empty dict when file doesn't exist."""
    manifest = security_policy._load_manifest()
    assert manifest == {}


def test_load_manifest_from_file(security_policy, temp_user_dir):
    """Test loading manifest from file."""
    manifest_data = {"script1.py": "abc123", "script2.py": "def456"}
    (temp_user_dir / "scripts" / ".manifest.json").write_text(json.dumps(manifest_data))

    manifest = security_policy._load_manifest()
    assert manifest == manifest_data


def test_sign_resigns_existing_script(security_policy, temp_user_dir):
    """Test that signing a script twice updates the manifest."""
    script_file = temp_user_dir / "scripts" / "test.py"
    script_file.write_text("print('v1')")

    # Sign v1
    security_policy.sign_script(script_file)
    with open(security_policy.manifest_file) as f:
        manifest_v1 = json.load(f)
    hash_v1 = manifest_v1["test.py"]

    # Update script
    script_file.write_text("print('v2')")

    # Sign v2
    security_policy.sign_script(script_file)
    with open(security_policy.manifest_file) as f:
        manifest_v2 = json.load(f)
    hash_v2 = manifest_v2["test.py"]

    # Hashes should be different
    assert hash_v1 != hash_v2


def test_security_policy_with_missing_config(temp_user_dir):
    """Test SecurityPolicy when config.yaml doesn't exist."""
    (temp_user_dir / "config.yaml").unlink()

    policy = SecurityPolicy(temp_user_dir)
    assert policy.allows_python_scripts() is True  # Default value


def test_config_with_invalid_yaml(security_policy, temp_user_dir):
    """Test that invalid YAML is handled gracefully."""
    (temp_user_dir / "config.yaml").write_text("invalid: yaml: content: [")
    security_policy._config_cache = None

    # Should return default, not crash
    result = security_policy.allows_python_scripts()
    assert result is True


def test_multiple_scripts_signed(security_policy, temp_user_dir):
    """Test signing multiple scripts."""
    scripts = ["script1.py", "script2.py", "script3.py"]

    for i, script_name in enumerate(scripts):
        script_file = temp_user_dir / "scripts" / script_name
        script_file.write_text(f"print('script{i}')")
        security_policy.sign_script(script_file)

    manifest = security_policy._load_manifest()
    assert len(manifest) == 3
    for script_name in scripts:
        assert script_name in manifest
