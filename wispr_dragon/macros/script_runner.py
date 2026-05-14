"""Execute signed Python scripts with security checks."""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .security import SecurityPolicy

logger = logging.getLogger(__name__)


class ScriptRunner:
    """Runs signed Python scripts in isolated subprocesses."""

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

        Args:
            script_name: Name of script file (e.g., "my_script.py")
            timeout: Maximum execution time in seconds
            env: Environment variables to pass to script

        Returns:
            stdout output from the script, or None on error
        """
        if not self.security.allows_python_scripts():
            logger.error("Python scripts are disabled by security policy")
            return None

        script_path = self.scripts_dir / script_name

        # Verify script exists
        if not script_path.exists():
            logger.error("Script not found: %s", script_name)
            return None

        # Verify script signature
        if not self.security.check_script_signature(script_path):
            logger.error("Script signature check failed: %s", script_name)
            return None

        # Run in subprocess with timeout
        try:
            logger.info("Running script: %s", script_name)
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env or {},
            )

            if result.returncode != 0:
                logger.error("Script failed with code %d: %s", result.returncode, result.stderr)
                return None

            logger.debug("Script output: %s", result.stdout)
            return result.stdout

        except subprocess.TimeoutExpired:
            logger.error("Script execution timed out: %s", script_name)
            return None
        except Exception as e:
            logger.error("Failed to execute script: %s", e)
            return None
