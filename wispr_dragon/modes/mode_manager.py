"""Mode management for dictation and command modes."""

import logging
from enum import Enum, auto
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class Mode(Enum):
    DICTATION = auto()
    COMMAND = auto()
    SLEEP = auto()


# Commands that work in ANY mode
ALWAYS_ON_COMMANDS = {
    "scratch that": "undo_last",
    "correct that": "open_correction_window",
    "go to sleep": "sleep_mode",
    "wake up": "wake_mode",
    "switch to command mode": "switch_command",
    "switch to dictation mode": "switch_dictation",
}


class ModeManager:
    """Manages switching between dictation and command modes.

    Always-on commands (scratch that, correct that, etc.) work
    regardless of the current mode.
    """

    def __init__(self, macro_runner=None):
        self._mode = Mode.DICTATION
        self._handlers: dict[str, Callable] = {}
        self._undo_buffer: list[str] = []
        self._max_undo = 20
        self._macro_runner = macro_runner

    @property
    def mode(self) -> Mode:
        return self._mode

    def register_handler(self, action: str, handler: Callable) -> None:
        """Register a handler function for a command action."""
        self._handlers[action] = handler

    def process_text(self, text: str) -> Optional[str]:
        """Process transcribed text based on the current mode.

        Returns:
            Text to output (dictation mode), or None if handled as command.
        """
        text_lower = text.lower().strip()

        # Check always-on commands first (whole-word boundary match only)
        for trigger, action in ALWAYS_ON_COMMANDS.items():
            if text_lower == trigger or (
                text_lower.startswith(trigger)
                and (len(text_lower) == len(trigger) or not text_lower[len(trigger)].isalpha())
            ):
                return self._execute_action(action, text)

        if self._mode == Mode.SLEEP:
            return None

        if self._mode == Mode.COMMAND:
            return self._handle_command(text)

        # Dictation mode: return text for output
        self._undo_buffer.append(text)
        if len(self._undo_buffer) > self._max_undo:
            self._undo_buffer.pop(0)
        return text

    def _handle_command(self, text: str) -> Optional[str]:
        """Handle text in command mode."""
        from .command_mode import match_command

        # Check for macros first
        if self._macro_runner:
            macro = self._macro_runner.find_macro(text)
            if macro:
                return self._execute_action("macro", text, {"macro": macro})

        # Fall back to built-in commands
        action = match_command(text)
        if action:
            return self._execute_action(action["action"], text, action.get("args"))
        logger.debug("No command matched: '%s'", text)
        return None

    def _execute_action(self, action: str, text: str,
                        args: Optional[dict] = None) -> Optional[str]:
        """Execute a command action."""
        if action == "sleep_mode":
            self._mode = Mode.SLEEP
            logger.info("Entering sleep mode")
            return None
        elif action == "wake_mode":
            self._mode = Mode.DICTATION
            logger.info("Waking up to dictation mode")
            return None
        elif action == "switch_command":
            self._mode = Mode.COMMAND
            logger.info("Switched to command mode")
            return None
        elif action == "switch_dictation":
            self._mode = Mode.DICTATION
            logger.info("Switched to dictation mode")
            return None
        elif action == "undo_last":
            if self._undo_buffer:
                undone = self._undo_buffer.pop()
                handler = self._handlers.get("undo_last")
                if handler:
                    handler(undone)
                logger.info("Undid: '%s'", undone)
            return None

        handler = self._handlers.get(action)
        if handler:
            handler(text, args)
            return None

        logger.warning("No handler for action: %s", action)
        return None
