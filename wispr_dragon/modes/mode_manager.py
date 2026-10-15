"""Mode management for dictation and command modes."""

import logging
from enum import Enum, auto
from typing import Callable, Optional

from .triggers import normalize_phrase

logger = logging.getLogger(__name__)


class Mode(Enum):
    DICTATION = auto()
    COMMAND = auto()
    SLEEP = auto()
    SPELLING = auto()
    NUMBERS = auto()


# Commands that work in ANY mode
ALWAYS_ON_COMMANDS = {
    "scratch that": "undo_last",
    "correct that": "open_correction_window",
    "go to sleep": "sleep_mode",
    "wake up": "wake_mode",
    "switch to command mode": "switch_command",
    "switch to dictation mode": "switch_dictation",
    "start spelling": "switch_spelling",
    "spelling mode": "switch_spelling",
    "stop spelling": "switch_dictation",
    "start numbers": "switch_numbers",
    "numbers mode": "switch_numbers",
    "stop numbers": "switch_dictation",
}

# Actions that stay available in dictation-only mode: they only steer or edit
# dictation. Anything else (command mode, keystrokes, macros, custom handlers)
# is blocked when dictation-only is on.
_DICTATION_SAFE_ACTIONS = frozenset({
    "sleep_mode",
    "wake_mode",
    "switch_dictation",
    "switch_spelling",
    "switch_numbers",
    "undo_last",
    "open_correction_window",
})


class ModeManager:
    """Manages switching between dictation and command modes.

    Always-on commands (scratch that, correct that, etc.) work in every mode
    except SLEEP, where only "wake up" is honoured (as in Dragon). They fire
    only when they are the whole utterance, so "Scratch that itch." is dictated.

    Args:
        macro_runner: optional MacroRunner for command-mode macros. Its
            security policy is also consulted for dictation-only mode.
        dictation_only: block command mode, keystrokes and macros outright
            (e.g. from ``--dictation-only``).
    """

    def __init__(self, macro_runner=None, dictation_only: bool = False):
        self._mode = Mode.DICTATION
        self._handlers: dict[str, Callable] = {}
        self._undo_buffer: list[str] = []
        self._max_undo = 20
        self._macro_runner = macro_runner
        self._dictation_only = bool(dictation_only)
        self._on_mode_change: Optional[Callable[["Mode"], None]] = None

    @property
    def mode(self) -> Mode:
        return self._mode

    def register_handler(self, action: str, handler: Callable) -> None:
        """Register a handler function for a command action."""
        self._handlers[action] = handler

    def set_mode_change_callback(self, callback: Optional[Callable[["Mode"], None]]) -> None:
        """Register a callback fired with the new Mode whenever the mode changes.

        Used to drive the mic-state indicator (sleep -> standby, wake -> hot).
        Called on whatever thread processes the triggering utterance.
        """
        self._on_mode_change = callback

    def _set_mode(self, mode: "Mode") -> None:
        """Set the active mode and notify the mode-change callback on a change."""
        if mode == self._mode:
            return
        self._mode = mode
        if self._on_mode_change:
            try:
                self._on_mode_change(mode)
            except Exception as e:
                logger.error("Mode-change callback failed: %s", e)

    def is_dictation_only(self) -> bool:
        """True if commands/keystrokes/macros must not fire.

        Set explicitly, or reported by the macro runner's SecurityPolicy (which
        sees config, ``--dictation-only`` and the admin lock). A policy that
        errors fails closed.
        """
        if self._dictation_only:
            return True
        security = getattr(self._macro_runner, "security", None)
        if security is None:
            return False
        try:
            return security.is_dictation_only() is True
        except Exception as e:
            logger.error("Security policy check failed; assuming dictation-only: %s", e)
            return True

    def record_output(self, text: str) -> None:
        """Record text that was actually emitted, so "scratch that" can undo it.

        Callers pass the final text exactly as rendered/injected (after any
        spelling/numbers transform, plus any separator they appended) so the
        undo removes the right number of characters.
        """
        if not text or not text.strip():
            return
        self._undo_buffer.append(text)
        if len(self._undo_buffer) > self._max_undo:
            self._undo_buffer.pop(0)

    def process_text(self, text: str) -> Optional[str]:
        """Process transcribed text based on the current mode.

        Returns:
            Text to output (dictation mode), or None if handled as command.
            Output is not recorded for undo here; the caller records what it
            actually emits via :meth:`record_output`.
        """
        # Always-on commands must be the whole utterance (punctuation and
        # spacing ignored) -- never a prefix of an ordinary sentence.
        action = ALWAYS_ON_COMMANDS.get(normalize_phrase(text))

        if self._mode == Mode.SLEEP:
            # Asleep: only "wake up" is heard; everything else is swallowed.
            if action == "wake_mode":
                return self._execute_action(action, text)
            return None

        if action:
            return self._execute_action(action, text)

        if self._mode == Mode.COMMAND:
            return self._handle_command(text)

        # DICTATION, SPELLING, NUMBERS: the text is output (the orchestrator
        # applies the mode's transform).
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
        if action not in _DICTATION_SAFE_ACTIONS and self.is_dictation_only():
            logger.warning("Blocked '%s': dictation-only mode is enabled", action)
            return None

        if action == "sleep_mode":
            self._set_mode(Mode.SLEEP)
            logger.info("Entering sleep mode")
            return None
        elif action == "wake_mode":
            self._set_mode(Mode.DICTATION)
            logger.info("Waking up to dictation mode")
            return None
        elif action == "switch_command":
            self._set_mode(Mode.COMMAND)
            logger.info("Switched to command mode")
            return None
        elif action == "switch_dictation":
            self._set_mode(Mode.DICTATION)
            logger.info("Switched to dictation mode")
            return None
        elif action == "switch_spelling":
            self._set_mode(Mode.SPELLING)
            logger.info("Switched to spelling mode")
            return None
        elif action == "switch_numbers":
            self._set_mode(Mode.NUMBERS)
            logger.info("Switched to numbers mode")
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
