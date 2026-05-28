"""Execute YAML macros and Python scripts triggered by voice commands."""

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from .security import SecurityPolicy
from .script_runner import ScriptRunner

logger = logging.getLogger(__name__)


class MacroRunner:
    """Executes voice-triggered macros and scripts.

    Macro actions:
    - keystroke: Send keyboard input via xdotool
    - text: Inject text via TextInjector
    - launch: Start a program
    - python_script: Execute a signed Python script
    """

    def __init__(self, user_dir: Path, text_injector=None):
        """Initialize macro runner.

        Args:
            user_dir: User config directory (~/.wispr_dragon)
            text_injector: TextInjector instance for text injection actions
        """
        self.user_dir = user_dir
        self.macros_dir = user_dir / "macros"
        self.scripts_dir = user_dir / "scripts"
        self.text_injector = text_injector

        self.security = SecurityPolicy(user_dir)
        self.script_runner = ScriptRunner(self.scripts_dir, self.security)

        self._macros_cache = {}
        self._load_macros()

    def execute(self, macro: dict, captured_args: Optional[dict] = None) -> bool:
        """Execute a macro with optional placeholder arguments.

        Args:
            macro: Macro dict with 'action' key and action-specific fields
            captured_args: Dict of captured placeholder values (e.g., {'app': 'firefox'})

        Returns:
            True on success, False on error
        """
        action = macro.get("action", "").lower()

        if not action:
            logger.error("Macro has no action")
            return False

        # Check security policy
        if action in ("keystroke", "text", "launch", "python_script"):
            if self.security.is_dictation_only():
                logger.warning("Macro execution blocked: dictation-only mode enabled")
                return False

        try:
            if action == "keystroke":
                return self._execute_keystroke(macro)
            elif action == "text":
                return self._execute_text(macro)
            elif action == "launch":
                return self._execute_launch(macro, captured_args)
            elif action == "python_script":
                return self._execute_python_script(macro)
            else:
                logger.error("Unknown action: %s", action)
                return False

        except Exception as e:
            logger.error("Failed to execute macro: %s", e)
            return False

    def _execute_keystroke(self, macro: dict) -> bool:
        """Execute keystroke action."""
        keys = macro.get("keys", "").strip()
        if not keys:
            logger.error("Keystroke action missing 'keys' field")
            return False

        # Validate keystroke pattern (same as in main.py)
        if not re.match(r"^[a-zA-Z0-9+\-_]+$", keys):
            logger.error("Invalid keystroke pattern: %s", keys)
            return False

        try:
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", keys],
                timeout=2,
                check=False,
            )
            logger.debug("Keystroke executed: %s", keys)
            return True
        except FileNotFoundError:
            logger.error("xdotool not found")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Keystroke command timed out")
            return False

    def _execute_text(self, macro: dict) -> bool:
        """Execute text injection action."""
        if not self.text_injector:
            logger.error("Text injector not configured")
            return False

        content = macro.get("content", "")
        if not content:
            logger.error("Text action missing 'content' field")
            return False

        try:
            self.text_injector.inject(content)
            logger.debug("Text injected: %d chars", len(content))
            return True
        except Exception as e:
            logger.error("Text injection failed: %s", e)
            return False

    def _execute_launch(self, macro: dict, captured_args: Optional[dict] = None) -> bool:
        """Execute program launch action."""
        if not self.security.allows_program_launch():
            logger.error("Program launching is disabled by security policy")
            return False

        program = macro.get("program", "").strip()
        if not program:
            logger.error("Launch action missing 'program' field")
            return False

        # If program has placeholder, substitute from captured_args
        if "{" in program and captured_args:
            program = self._substitute_placeholders(program, captured_args)

        # Verify program exists via PATH
        if not shutil.which(program):
            logger.error("Program not found in PATH: %s", program)
            return False

        # Get optional args
        args = macro.get("args", [])
        if isinstance(args, str):
            args = [args]

        cmd = [program] + list(args)

        try:
            subprocess.Popen(cmd)
            logger.info("Program launched: %s", program)
            return True
        except Exception as e:
            logger.error("Failed to launch program: %s", e)
            return False

    def _execute_python_script(self, macro: dict) -> bool:
        """Execute Python script action."""
        if not self.security.allows_python_scripts():
            logger.error("Python scripts are disabled by security policy")
            return False

        script_name = macro.get("script", "").strip()
        if not script_name:
            logger.error("Python script action missing 'script' field")
            return False

        # Run script
        output = self.script_runner.run_script(script_name, timeout=30)
        if output is None:
            return False

        # If script outputs text and we have text injector, inject it
        if output.strip() and self.text_injector:
            try:
                self.text_injector.inject(output)
                logger.debug("Script output injected: %d chars", len(output))
            except Exception as e:
                logger.warning("Failed to inject script output: %s", e)

        return True

    def _load_macros(self) -> None:
        """Load all macros from YAML files in macros directory."""
        if not self.macros_dir.exists():
            logger.warning("Macros directory not found: %s", self.macros_dir)
            return

        self._macros_cache.clear()

        for yaml_file in self.macros_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}

                macros_list = data.get("macros", [])
                for macro in macros_list:
                    trigger = macro.get("trigger", "").lower()
                    if trigger:
                        self._macros_cache[trigger] = macro
                        logger.debug("Loaded macro: %s", trigger)

            except Exception as e:
                logger.error("Failed to load macros from %s: %s", yaml_file, e)

        logger.info("Loaded %d macros", len(self._macros_cache))

    def find_macro(self, text: str) -> Optional[dict]:
        """Find a macro that matches the given text.

        Supports exact matching and placeholder extraction.

        Args:
            text: Voice-recognized text (e.g., "open firefox")

        Returns:
            Macro dict with 'trigger' and 'action', or None if not found
        """
        text_lower = text.lower().strip()

        # Exact match
        if text_lower in self._macros_cache:
            return self._macros_cache[text_lower]

        # Placeholder match (e.g., "open {app}")
        for trigger, macro in self._macros_cache.items():
            if "{" in trigger:
                pattern = re.escape(trigger).replace(r"\{", "(?P<").replace(r"\}", r">[\w\s]+)")
                match = re.match(pattern, text_lower, re.IGNORECASE)
                if match:
                    macro = dict(macro)
                    macro["_captured_args"] = match.groupdict()
                    return macro

        return None

    def reload_macros(self) -> None:
        """Reload all macros from disk."""
        logger.info("Reloading macros")
        self._load_macros()

    def _substitute_placeholders(self, text: str, values: dict) -> str:
        """Substitute placeholders in text with provided values."""
        for key, value in values.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text
