"""Run signed Python scripts in a hash-pinned, time-limited subprocess."""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .security import SecurityPolicy, is_safe_script_name

logger = logging.getLogger(__name__)

# Environment passed through to scripts: just enough for the interpreter to
# start on every platform (Windows needs SYSTEMROOT; tempfile wants TEMP/TMP).
_PASSTHROUGH_ENV = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR")


def _minimal_env() -> dict:
    return {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}


class ScriptRunner:
    """Runs signed Python scripts as hash-pinned, time-limited subprocesses.

    This is not a sandbox: a signed script runs with the user's privileges.
    What it guarantees is that only the exact bytes that were signed execute
    (no swap between verification and launch), in an isolated-mode interpreter
    (``-I``: no PYTHON* env vars, user site-packages or script dir on
    sys.path), with a minimal environment and a timeout.
    """

    def __init__(self, scripts_dir: Path, security: SecurityPolicy):
        """Initialize script runner.

        Args:
            scripts_dir: Directory containing scripts (~/.wispr_dragon/scripts)
            security: SecurityPolicy instance for signature verification
        """
        self.scripts_dir = scripts_dir
        self.security = security

    def run_script(
        self,
        script_name: str,
        timeout: int = 30,
        env: Optional[dict] = None,
    ) -> Optional[str]:
        """Run a signed Python script.

        The file is read once; the hash is checked against those bytes and the
        same bytes are fed to the interpreter on stdin. Consequently the script
        sees ``__file__ == "<stdin>"`` and cannot read stdin itself.

        Args:
            script_name: Bare file name inside the scripts dir (e.g. "my_script.py")
            timeout: Maximum execution time in seconds
            env: Extra environment variables for the script (merged over a
                minimal PATH/SYSTEMROOT/TEMP environment)

        Returns:
            stdout output from the script, or None on error
        """
        if not self.security.allows_python_scripts():
            logger.error("Python scripts are disabled by security policy")
            return None

        if not is_safe_script_name(script_name):
            logger.error("Refusing script name that is not a bare file name: %r", script_name)
            return None

        script_path = self.scripts_dir / script_name
        try:
            data = script_path.read_bytes()
        except FileNotFoundError:
            logger.error("Script not found: %s", script_name)
            return None
        except OSError as e:
            logger.error("Failed to read script %s: %s", script_name, e)
            return None

        # Verify the signature of exactly the bytes we are about to run.
        if not self.security.check_script_bytes(script_name, data):
            logger.error("Script signature check failed: %s", script_name)
            return None

        run_env = _minimal_env()
        if env:
            run_env.update(env)

        try:
            logger.info("Running script: %s", script_name)
            result = subprocess.run(
                [sys.executable, "-I", "-X", "utf8", "-"],
                input=data,
                capture_output=True,
                timeout=timeout,
                env=run_env,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            if result.returncode != 0:
                logger.error("Script failed with code %d: %s", result.returncode, stderr)
                return None

            logger.debug("Script output: %s", stdout)
            return stdout

        except subprocess.TimeoutExpired:
            logger.error("Script execution timed out: %s", script_name)
            return None
        except Exception as e:
            logger.error("Failed to execute script: %s", e)
            return None
