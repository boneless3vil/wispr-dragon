"""Command mode grammar matching."""

import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

DEFAULT_COMMANDS_PATH = Path.home() / ".wispr_dragon" / "commands.yaml"
BUILTIN_COMMANDS_PATH = Path(__file__).parent.parent.parent / "data" / "default_commands.yaml"

_commands: list[dict] = []


def load_commands(user_path: Optional[Path] = None) -> None:
    """Load command definitions from YAML files."""
    global _commands
    _commands = []

    # Load built-in commands
    if BUILTIN_COMMANDS_PATH.exists():
        with open(BUILTIN_COMMANDS_PATH) as f:
            data = yaml.safe_load(f) or {}
        _commands.extend(data.get("commands", []))

    # Load user commands (override built-in)
    user_path = user_path or DEFAULT_COMMANDS_PATH
    if user_path.exists():
        with open(user_path) as f:
            data = yaml.safe_load(f) or {}
        _commands.extend(data.get("commands", []))

    logger.info("Loaded %d commands", len(_commands))


def match_command(text: str, threshold: int = 80) -> Optional[dict]:
    """Match transcribed text against the command grammar.

    Supports exact matching, fuzzy matching, and placeholder extraction.
    """
    text_lower = text.lower().strip()

    if not _commands:
        load_commands()

    _STRUCTURAL_KEYS = {"trigger", "action", "description"}

    def _make_result(cmd: dict, extra_args: Optional[dict] = None) -> dict:
        """Build a result dict, pulling non-structural YAML fields into args."""
        result = dict(cmd)
        args = {k: v for k, v in cmd.items() if k not in _STRUCTURAL_KEYS}
        if extra_args:
            args.update(extra_args)
        result["args"] = args
        return result

    # Try exact match first
    for cmd in _commands:
        trigger = cmd.get("trigger", "").lower()
        if text_lower == trigger:
            return _make_result(cmd)

    # Try placeholder matching (e.g., "correct {word}")
    for cmd in _commands:
        trigger = cmd.get("trigger", "")
        if "{" in trigger:
            pattern = re.escape(trigger).replace(r"\{", "(?P<").replace(r"\}", r">[\w\s]+)")
            match = re.match(pattern, text_lower, re.IGNORECASE)
            if match:
                return _make_result(cmd, extra_args=match.groupdict())

    # Fuzzy match
    best_score = 0
    best_cmd = None
    for cmd in _commands:
        trigger = cmd.get("trigger", "").lower()
        score = fuzz.ratio(text_lower, trigger)
        if score > best_score and score >= threshold:
            best_score = score
            best_cmd = cmd

    return _make_result(best_cmd) if best_cmd else None
