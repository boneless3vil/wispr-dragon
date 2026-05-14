"""Security policy enforcement for macros and scripts."""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SecurityPolicy:
    """Manages security settings with 3-layer enforcement.

    Layer 1: Config flags (allow_python_scripts, allow_yaml_macros, allow_program_launch)
    Layer 2: Password-protected lock file (overrides config)
    Layer 3: Script signing with SHA-256 manifest
    """

    def __init__(self, user_dir: Path):
        """Initialize security policy.

        Args:
            user_dir: User config directory (~/.wispr_dragon)
        """
        self.user_dir = user_dir
        self.config_file = user_dir / "config.yaml"
        self.lock_file = user_dir / "security.lock"
        self.scripts_dir = user_dir / "scripts"
        self.manifest_file = self.scripts_dir / ".manifest.json"

        self._config_cache = None
        self._lock_cache = None

    def allows_python_scripts(self) -> bool:
        """Check if Python scripts are allowed."""
        # Layer 2 (lock) overrides Layer 1 (config)
        if self.lock_file.exists():
            lock_policy = self._load_lock()
            if lock_policy and "allow_python_scripts" in lock_policy:
                return lock_policy["allow_python_scripts"]

        # Default to Layer 1 (config)
        return self._get_config_setting("security", {}).get("allow_python_scripts", True)

    def allows_yaml_macros(self) -> bool:
        """Check if YAML macros are allowed."""
        if self.lock_file.exists():
            lock_policy = self._load_lock()
            if lock_policy and "allow_yaml_macros" in lock_policy:
                return lock_policy["allow_yaml_macros"]

        return self._get_config_setting("security", {}).get("allow_yaml_macros", True)

    def allows_program_launch(self) -> bool:
        """Check if program launching is allowed."""
        if self.lock_file.exists():
            lock_policy = self._load_lock()
            if lock_policy and "allow_program_launch" in lock_policy:
                return lock_policy["allow_program_launch"]

        return self._get_config_setting("security", {}).get("allow_program_launch", True)

    def is_dictation_only(self) -> bool:
        """Check if only dictation is allowed (no commands/macros)."""
        if self.lock_file.exists():
            lock_policy = self._load_lock()
            if lock_policy and "dictation_only" in lock_policy:
                return lock_policy["dictation_only"]

        return self._get_config_setting("security", {}).get("dictation_only", False)

    def is_locked(self) -> bool:
        """Check if admin lock is active."""
        return self.lock_file.exists()

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

        manifest = self._load_manifest()
        script_name = script_path.name

        if script_name not in manifest:
            logger.error("Script not signed: %s", script_name)
            return False

        stored_hash = manifest[script_name]
        actual_hash = self._hash_file(script_path)

        if stored_hash != actual_hash:
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

    def remove_admin_lock(self, password_hash: str) -> bool:
        """Remove admin lock after verifying password.

        Args:
            password_hash: bcrypt hash to verify against stored hash

        Returns:
            True if password matches and lock is removed
        """
        if not self.lock_file.exists():
            logger.warning("No admin lock to remove")
            return False

        lock_data = self._load_lock()
        if not lock_data:
            return False

        if lock_data.get("password_hash") != password_hash:
            logger.error("Admin password mismatch")
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
            with open(self.config_file) as f:
                config = yaml.safe_load(f) or {}
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
            self._lock_cache = data.get("policy", {})
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
                return json.load(f)
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
