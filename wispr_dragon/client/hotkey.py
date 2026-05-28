"""Global hotkey listener for the Windows client.

Two modes:

* ``HotkeyMode.PTT`` (push-to-talk) — active only while the hotkey is held.
* ``HotkeyMode.TOGGLE`` — pressing flips active on/off; release does nothing.

Keyboard hook uses pynput, which is imported lazily inside :meth:`Hotkey.start`
so this module is importable on systems without pynput (the state machine is
useful by itself for tests).
"""

from __future__ import annotations

import enum
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HotkeyMode(str, enum.Enum):
    PTT = "ptt"
    TOGGLE = "toggle"


class HotkeyStateMachine:
    """Pure state — no I/O, no pynput. Feed it press/release events.

    Each event method returns the resulting ``active`` value. Autorepeat is
    filtered: holding the key produces one "press" transition, regardless of
    how many on_press events the OS delivers.
    """

    def __init__(self, mode: HotkeyMode = HotkeyMode.PTT):
        self._mode = mode
        self._active = False
        self._key_down = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def mode(self) -> HotkeyMode:
        return self._mode

    @property
    def key_down(self) -> bool:
        return self._key_down

    def set_mode(self, mode: HotkeyMode) -> bool:
        """Switch modes. If switching to PTT while not holding the key,
        reset active to False so the mic doesn't get stuck on."""
        if mode == HotkeyMode.PTT and self._active and not self._key_down:
            self._active = False
        self._mode = mode
        return self._active

    def on_press(self) -> bool:
        # Drop OS-level autorepeat: only the first press of a hold counts.
        if self._key_down:
            return self._active
        self._key_down = True
        if self._mode == HotkeyMode.PTT:
            self._active = True
        else:  # TOGGLE
            self._active = not self._active
        return self._active

    def on_release(self) -> bool:
        if not self._key_down:
            return self._active
        self._key_down = False
        if self._mode == HotkeyMode.PTT:
            self._active = False
        return self._active


def _resolve_key(kb_module, name: str):
    """Translate a config string into a pynput Key or KeyCode.

    ``name`` may be either a ``pynput.keyboard.Key`` attribute (``'ctrl_r'``,
    ``'f8'``, ``'scroll_lock'``) or a single character (``'a'``).
    """
    name = name.lower().strip()
    if hasattr(kb_module.Key, name):
        return getattr(kb_module.Key, name)
    if len(name) == 1:
        return kb_module.KeyCode.from_char(name)
    raise ValueError(f"Unknown hotkey: {name!r}")


class Hotkey:
    """Global keyboard hotkey wrapping :class:`HotkeyStateMachine`.

    Callbacks fire on pynput's listener thread — bridge back to your event
    loop yourself if you need to touch thread-bound state.
    """

    def __init__(
        self,
        key_name: str = "ctrl_r",
        mode: HotkeyMode = HotkeyMode.PTT,
        on_active_changed: Optional[Callable[[bool], None]] = None,
    ):
        self._key_name = key_name
        self._state = HotkeyStateMachine(mode)
        self._on_active_changed = on_active_changed
        self._listener = None
        self._key = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._state.active

    @property
    def mode(self) -> HotkeyMode:
        return self._state.mode

    def start(self) -> None:
        """Start the global keyboard listener. Imports pynput on demand."""
        from pynput import keyboard  # lazy: keep this module importable on CI
        self._key = _resolve_key(keyboard, self._key_name)
        self._listener = keyboard.Listener(
            on_press=self._on_press_event,
            on_release=self._on_release_event,
        )
        self._listener.start()
        logger.info(
            "Hotkey listener started (key=%s mode=%s)",
            self._key_name, self._state.mode.value,
        )

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def set_mode(self, mode: HotkeyMode) -> None:
        with self._lock:
            prev = self._state.active
            self._state.set_mode(mode)
            if self._state.active != prev:
                self._notify(self._state.active)
        logger.info("Hotkey mode -> %s", mode.value)

    def _on_press_event(self, key) -> None:
        if key != self._key:
            return
        with self._lock:
            prev = self._state.active
            now = self._state.on_press()
        if now != prev:
            self._notify(now)

    def _on_release_event(self, key) -> None:
        if key != self._key:
            return
        with self._lock:
            prev = self._state.active
            now = self._state.on_release()
        if now != prev:
            self._notify(now)

    def _notify(self, active: bool) -> None:
        if self._on_active_changed is None:
            return
        try:
            self._on_active_changed(active)
        except Exception as e:
            logger.error("Hotkey callback raised: %s", e)
