"""Command mode grammar matching with thread-safe registry."""

import logging
from importlib import resources
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz

from .triggers import compile_trigger, has_placeholder, match_placeholder, normalize_utterance

logger = logging.getLogger(__name__)

DEFAULT_USER_DIR = Path.home() / ".wispr_dragon"
DEFAULT_COMMANDS_PATH = DEFAULT_USER_DIR / "commands.yaml"

_STRUCTURAL_KEYS = {"trigger", "action", "description"}


def builtin_commands_path():
    """Location of the built-in command grammar shipped inside the package.

    Lives at ``wispr_dragon/data/default_commands.yaml`` so it is present in
    wheels and frozen builds, not just a source checkout.
    """
    return resources.files("wispr_dragon") / "data" / "default_commands.yaml"


def _read_commands(source) -> list:
    """Read the ``commands:`` list from a YAML path/Traversable; [] on any problem."""
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error("Failed to load commands from %s: %s", source, e)
        return []
    commands = data.get("commands", []) if isinstance(data, dict) else []
    return [c for c in commands if isinstance(c, dict)] if isinstance(commands, list) else []


class CommandRegistry:
    """Thread-safe registry for voice commands.

    Manages loading and matching of built-in and user-defined commands.

    Args:
        user_dir: Directory holding the user's ``commands.yaml``
            (default: ``~/.wispr_dragon``).
    """

    def __init__(self, user_dir: Optional[Path] = None):
        self.commands: list[dict] = []
        self.user_dir = Path(user_dir) if user_dir else None
        self._loaded = False

    def load(self, user_path: Optional[Path] = None) -> None:
        """Load command definitions from YAML files.

        Args:
            user_path: Override path to user commands
                (default: ``<user_dir>/commands.yaml``)
        """
        commands = _read_commands(builtin_commands_path())
        if not commands:
            logger.warning("Built-in commands not found at %s", builtin_commands_path())

        # User commands are appended after (and can shadow) the built-ins.
        if user_path is None:
            user_path = self.user_dir / "commands.yaml" if self.user_dir else DEFAULT_COMMANDS_PATH
        user_path = Path(user_path)
        if user_path.is_file():
            commands.extend(_read_commands(user_path))

        # Compile placeholder triggers now so a malformed one is reported (and
        # skipped) at load time rather than at match time.
        for cmd in commands:
            trigger = cmd.get("trigger")
            if isinstance(trigger, str) and has_placeholder(trigger):
                compile_trigger(trigger)

        self.commands = commands
        self._loaded = True
        logger.info("Loaded %d commands", len(self.commands))

    def match(self, text: str, threshold: int = 80) -> Optional[dict]:
        """Match transcribed text against the command registry.

        Supports exact matching, fuzzy matching, and placeholder extraction.
        Trailing sentence punctuation from the recogniser is ignored.

        Args:
            text: Voice-recognized text to match
            threshold: Fuzzy match score threshold (0-100)

        Returns:
            Command dict with trigger, action, and extracted args, or None
        """
        text_norm = normalize_utterance(text)

        # Commands assigned directly (tests, callers) count as loaded; a load
        # that legitimately found nothing is not retried on every utterance.
        if not self._loaded and not self.commands:
            self.load()

        literal: list[tuple[str, dict]] = []
        placeholder: list[tuple[str, dict]] = []
        for cmd in self.commands:
            trigger = cmd.get("trigger", "")
            if not isinstance(trigger, str) or not trigger.strip():
                continue
            (placeholder if has_placeholder(trigger) else literal).append((trigger, cmd))

        # Try exact match first
        for trigger, cmd in literal:
            if text_norm == normalize_utterance(trigger):
                return self._make_result(cmd)

        # Try placeholder matching (e.g., "correct {word}")
        for trigger, cmd in placeholder:
            captured = match_placeholder(trigger, text_norm)
            if captured is not None:
                return self._make_result(cmd, extra_args=captured)

        # Fuzzy match (literal triggers only: a fuzzy hit on a placeholder
        # trigger would return a command with no captured args).
        best_score = 0
        best_cmd = None
        for trigger, cmd in literal:
            score = fuzz.ratio(text_norm, normalize_utterance(trigger))
            if score > best_score and score >= threshold:
                best_score = score
                best_cmd = cmd

        return self._make_result(best_cmd) if best_cmd else None

    @staticmethod
    def _make_result(cmd: dict, extra_args: Optional[dict] = None) -> dict:
        """Build a result dict, pulling non-structural YAML fields into args."""
        result = dict(cmd)
        args = {k: v for k, v in cmd.items() if k not in _STRUCTURAL_KEYS}
        if extra_args:
            args.update(extra_args)
        result["args"] = args
        return result


# Global instance for backward compatibility
_registry = CommandRegistry()


def load_commands(user_path: Optional[Path] = None, user_dir: Optional[Path] = None) -> None:
    """Load command definitions from YAML files (backward-compatible API).

    Args:
        user_path: Explicit user commands file (wins over ``user_dir``).
        user_dir: User config directory whose ``commands.yaml`` to load
            (default: ``~/.wispr_dragon``).
    """
    if user_dir is not None:
        _registry.user_dir = Path(user_dir)
    _registry.load(user_path)


def match_command(text: str, threshold: int = 80) -> Optional[dict]:
    """Match transcribed text against the command grammar (backward-compatible API)."""
    return _registry.match(text, threshold)
