"""Security policy enforcement for macros and scripts."""

import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default (permissive) value of each policy flag, and its restrictive value.
_POLICY_DEFAULTS = {
    "allow_python_scripts": True,
    "allow_yaml_macros": True,
    "allow_program_launch": True,
    "dictation_only": False,
}
_POLICY_RESTRICTIVE = {
    "allow_python_scripts": False,
    "allow_yaml_macros": False,
    "allow_program_launch": False,
    "dictation_only": True,
}


def is_safe_script_name(name: Any) -> bool:
    """True if ``name`` is a bare file name that stays inside the scripts dir.

    Rejects separators of either platform, absolute/drive paths, ``.``/``..``
    and colons (Windows drive-relative paths and NTFS streams), so a YAML
    ``script: ../../x.py`` can't point outside ``~/.wispr_dragon/scripts``.
    """
    if not isinstance(name, str) or not name or name in (".", ".."):
        return False
    if any(c in name for c in ("/", "\\", ":", "\x00")):
        return False
    path = Path(name)
    return not path.is_absolute() and not path.drive and path.name == name


def _as_policy_bool(key: str, value: Any, source: str) -> bool:
    """Accept only real booleans; anything else (e.g. the string "false")
    resolves to the restrictive setting instead of being truthy."""
    if isinstance(value, bool):
        return value
    logger.warning(
        "Security %s has non-boolean %s=%r; using the restrictive value", source, key, value
    )
    return _POLICY_RESTRICTIVE[key]


class SecurityPolicy:
    """Manages security settings with 3-layer enforcement.

    Layer 1: Config flags (allow_python_scripts, allow_yaml_macros,
             allow_program_launch, dictation_only): the in-memory
             SecurityConfig when given (so ``--config`` and CLI flags such as
             ``--dictation-only`` apply), else ``<user_dir>/config.yaml``.
    Layer 2: Password-protected lock file. It overrides config in the
             restrictive direction: config can still tighten a locked policy
             but never loosen it. A lock that can't be parsed, or that holds
             a non-boolean value, fails closed.
    Layer 3: Script signing with SHA-256 manifest
    """

    def __init__(self, user_dir: Path, security_cfg=None):
        """Initialize security policy.

        Args:
            user_dir: User config directory (~/.wispr_dragon)
            security_cfg: Optional in-memory ``config.SecurityConfig``. When
                given it is used instead of re-reading config.yaml from disk.
        """
        self.user_dir = user_dir
        self.config_file = user_dir / "config.yaml"
        self.lock_file = user_dir / "security.lock"
        self.scripts_dir = user_dir / "scripts"
        self.manifest_file = self.scripts_dir / ".manifest.json"
        self.security_cfg = security_cfg

        self._config_cache = None
        self._lock_cache = None

    def allows_python_scripts(self) -> bool:
        """Check if Python scripts are allowed."""
        return self._policy("allow_python_scripts")

    def allows_yaml_macros(self) -> bool:
        """Check if YAML macros are allowed."""
        return self._policy("allow_yaml_macros")

    def allows_program_launch(self) -> bool:
        """Check if program launching is allowed."""
        return self._policy("allow_program_launch")

    def is_dictation_only(self) -> bool:
        """Check if only dictation is allowed (no commands/macros)."""
        return self._policy("dictation_only")

    def effective_policy(self) -> dict:
        """Snapshot of the policy currently in force (config + lock)."""
        return {key: self._policy(key) for key in _POLICY_DEFAULTS}

    def is_locked(self) -> bool:
        """Check if admin lock is active."""
        return self.lock_file.exists()

    def _policy(self, key: str) -> bool:
        """Resolve one flag: config value, tightened (never loosened) by the lock."""
        value = self._config_value(key)
        lock_value = self._lock_value(key)
        if lock_value is not None and lock_value == _POLICY_RESTRICTIVE[key]:
            return lock_value
        return value

    def _config_value(self, key: str) -> bool:
        if self.security_cfg is not None:
            raw = getattr(self.security_cfg, key, _POLICY_DEFAULTS[key])
            return _as_policy_bool(key, raw, "config")
        section = self._get_config_setting("security", {})
        if not isinstance(section, dict):
            return _POLICY_DEFAULTS[key]
        return _as_policy_bool(key, section.get(key, _POLICY_DEFAULTS[key]), "config.yaml")

    def _lock_value(self, key: str) -> Optional[bool]:
        """The lock's value for ``key``; None if unlocked or the key is unset."""
        if not self.lock_file.exists():
            return None
        lock_data = self._load_lock()
        policy = lock_data.get("policy") if isinstance(lock_data, dict) else None
        if not isinstance(policy, dict):
            logger.error("Admin lock file is unreadable or malformed; failing closed")
            return _POLICY_RESTRICTIVE[key]
        if key not in policy:
            return None
        return _as_policy_bool(key, policy[key], "lock")

    def check_script_signature(self, script_path: Path) -> bool:
        """Verify a script against the signed manifest.

        Args:
            script_path: Path to the script file

        Returns:
            True if script is signed and valid, False otherwise
        """
        if not script_path.exists():
            logger.error("Script not found: %s", script_path)
            return False
        try:
            data = script_path.read_bytes()
        except OSError as e:
            logger.error("Failed to read script %s: %s", script_path, e)
            return False
        return self.check_script_bytes(script_path.name, data)

    def check_script_bytes(self, script_name: str, data: bytes) -> bool:
        """Verify already-read script bytes against the manifest entry for
        ``script_name``. Callers then execute exactly these bytes, so the file
        can't be swapped between the check and the run."""
        stored_hash = self._load_manifest().get(script_name)
        if not isinstance(stored_hash, str) or not stored_hash:
            logger.error("Script not signed: %s", script_name)
            return False

        actual_hash = hashlib.sha256(data).hexdigest()
        if not hmac.compare_digest(stored_hash, actual_hash):
            logger.error("Script signature mismatch (modified?): %s", script_name)
            return False

        logger.debug("Script signature valid: %s", script_name)
        return True

    def sign_script(self, script_path: Path) -> bool:
        """Sign/re-sign a script by adding it to the manifest.

        Args:
            script_path: Path to the script file

        Returns:
            True on success, False on failure
        """
        if not script_path.exists():
            logger.error("Script not found: %s", script_path)
            return False

        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir.chmod(0o700)

        manifest = self._load_manifest()
        script_name = script_path.name
        file_hash = self._hash_file(script_path)
        manifest[script_name] = file_hash

        try:
            with open(self.manifest_file, "w") as f:
                json.dump(manifest, f, indent=2)
            self.manifest_file.chmod(0o600)
            logger.info("Script signed: %s (%s)", script_name, file_hash[:8])
            return True
        except Exception as e:
            logger.error("Failed to sign script: %s", e)
            return False

    def set_admin_lock(self, password_hash: str, policy: dict) -> bool:
        """Set an admin lock with password and policy.

        Args:
            password_hash: bcrypt hash of admin password
            policy: Dict with allow_* settings and dictation_only

        Returns:
            True on success
        """
        lock_data = {
            "password_hash": password_hash,
            "policy": policy,
        }

        try:
            self.user_dir.mkdir(parents=True, exist_ok=True)
            with open(self.lock_file, "w") as f:
                json.dump(lock_data, f, indent=2)
            self.lock_file.chmod(0o600)
            logger.info("Admin lock set")
            self._lock_cache = None
            return True
        except Exception as e:
            logger.error("Failed to set admin lock: %s", e)
            return False

    def verify_admin_password(self, password: str) -> bool:
        """Check ``password`` against the active lock's bcrypt hash.

        False if there is no lock, the lock is unreadable, or the hash is bad.
        """
        import bcrypt

        if not self.lock_file.exists():
            return False
        lock_data = self._load_lock()
        if not isinstance(lock_data, dict):
            return False

        stored_hash = lock_data.get("password_hash", "")
        try:
            if not isinstance(stored_hash, str) or not stored_hash or not bcrypt.checkpw(
                password.encode(), stored_hash.encode()
            ):
                logger.error("Admin password mismatch")
                return False
        except ValueError:
            logger.error("Stored admin password hash is malformed")
            return False
        return True

    def remove_admin_lock(self, password: str) -> bool:
        """Remove admin lock after verifying the admin password.

        Args:
            password: Plaintext admin password, verified against the stored
                bcrypt hash. (A pre-computed hash cannot be used here — bcrypt
                salts every hash, so two hashes of the same password differ.)

        Returns:
            True if the password matches and the lock is removed
        """
        if not self.lock_file.exists():
            logger.warning("No admin lock to remove")
            return False

        if not self.verify_admin_password(password):
            return False

        try:
            self.lock_file.unlink()
            logger.info("Admin lock removed")
            self._lock_cache = None
            return True
        except Exception as e:
            logger.error("Failed to remove admin lock: %s", e)
            return False

    def _get_config_setting(self, section: str, default: dict) -> dict:
        """Get a setting from config.yaml.

        Args:
            section: Top-level key in config (e.g., "security")
            default: Default value if not found

        Returns:
            Setting dict from config, or default
        """
        if not self.config_file.exists():
            return default

        try:
            import yaml
            with open(self.config_file, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            if not isinstance(config, dict):
                return default
            return config.get(section, default)
        except Exception as e:
            logger.warning("Failed to load config: %s", e)
            return default

    def _load_lock(self) -> Optional[dict]:
        """Load and parse the lock file."""
        if self._lock_cache is not None:
            return self._lock_cache

        if not self.lock_file.exists():
            return None

        try:
            with open(self.lock_file) as f:
                data = json.load(f)
            self._lock_cache = data
            return self._lock_cache
        except Exception as e:
            logger.error("Failed to load lock file: %s", e)
            return None

    def _load_manifest(self) -> dict:
        """Load the script signature manifest."""
        if not self.manifest_file.exists():
            return {}

        try:
            with open(self.manifest_file) as f:
                manifest = json.load(f)
            return manifest if isinstance(manifest, dict) else {}
        except Exception as e:
            logger.warning("Failed to load manifest: %s", e)
            return {}

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            sha256.update(f.read())
        return sha256.hexdigest()
