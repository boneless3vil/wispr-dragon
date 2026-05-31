"""Dragon-style microphone state model: OFF / STANDBY / HOT.

Dragon NaturallySpeaking surfaces a three-way mic indicator. We map it to our reality:

- **HOT**     — capturing audio and actively transcribing (any mode except sleep).
- **STANDBY** — mic open but asleep (``Mode.SLEEP``); ignores everything but "wake up".
- **OFF**     — not capturing.

``MicStateController`` is the single source of truth. Two inputs drive it: capture
start/stop (OFF <-> HOT) and mode transitions (sleep <-> wake => STANDBY <-> HOT).
Observers (the tray icon, the dictation-box dot) subscribe and are notified on change.

Threading: ``set_state`` may be called from any thread (mode changes fire on the
transcription worker thread). Observers that touch Qt widgets MUST re-emit to the
GUI thread themselves — this module does not marshal threads.
"""

import logging
from enum import Enum, auto
from typing import Callable, List

logger = logging.getLogger(__name__)


class MicState(Enum):
    OFF = auto()
    STANDBY = auto()
    HOT = auto()


class MicStateController:
    """Holds the current mic state and notifies observers on transitions."""

    def __init__(self, initial: MicState = MicState.OFF):
        self._state = initial
        self._observers: List[Callable[[MicState], None]] = []

    @property
    def state(self) -> MicState:
        return self._state

    def add_observer(self, callback: Callable[[MicState], None]) -> None:
        """Register a callback invoked with the new MicState on every change."""
        self._observers.append(callback)

    def set_state(self, state: MicState) -> None:
        """Set the state and notify observers (no-op if unchanged)."""
        if state == self._state:
            return
        self._state = state
        logger.debug("Mic state -> %s", state.name)
        for observer in list(self._observers):
            try:
                observer(state)
            except Exception as e:  # an observer must not break the others
                logger.error("Mic state observer failed: %s", e)

    def set_capturing(self, capturing: bool) -> None:
        """Capture on/off. Off => OFF; on => HOT (if previously OFF).

        Turning capture on from OFF goes HOT. It does not clobber an existing
        STANDBY (asleep) state — toggling capture shouldn't silently wake the mic.
        """
        if not capturing:
            self.set_state(MicState.OFF)
        elif self._state == MicState.OFF:
            self.set_state(MicState.HOT)

    def set_asleep(self, asleep: bool) -> None:
        """Map a sleep/wake mode transition to STANDBY <-> HOT.

        Ignored while OFF — sleep only makes sense for an open mic.
        """
        if self._state == MicState.OFF:
            return
        self.set_state(MicState.STANDBY if asleep else MicState.HOT)
