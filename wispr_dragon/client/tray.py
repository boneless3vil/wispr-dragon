"""System tray icon for the Windows client.

Tiny PyQt6 wrapper that exposes the hotkey mode as a checkable menu item and
a Quit action. Driven by the client — call :meth:`update_recording_state`
whenever the hotkey active state flips so the icon and label stay in sync.

This module is imported only when the tray UI is enabled (no ``--no-tray``),
so PyQt6 stays optional for headless runs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from wispr_dragon.client.hotkey import HotkeyMode

if TYPE_CHECKING:
    from wispr_dragon.client.app import WisprDragonClient

logger = logging.getLogger(__name__)


class TrayApp:
    """A system-tray icon + menu bound to a :class:`WisprDragonClient`.

    The client owns the hotkey and the audio capture; the tray is a thin view
    over them — it doesn't hold its own state.
    """

    def __init__(self, client: "WisprDragonClient"):
        self.client = client
        self.tray: QSystemTrayIcon | None = None
        self.menu: QMenu | None = None
        self.state_action: QAction | None = None
        self.toggle_action: QAction | None = None
        self.quit_action: QAction | None = None

    def start(self) -> None:
        """Build the tray icon + menu. Requires a QApplication to exist."""
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication must be constructed before TrayApp.start()")

        self.tray = QSystemTrayIcon(app)
        self.tray.setToolTip("Wispr Dragon — idle")
        self._refresh_icon(active=False)

        self.menu = QMenu()

        self.state_action = QAction("Recording: OFF")
        self.state_action.setEnabled(False)  # informational only
        self.menu.addAction(self.state_action)

        self.menu.addSeparator()

        self.toggle_action = QAction("Toggle mode  (press to start / stop)")
        self.toggle_action.setCheckable(True)
        self.toggle_action.setChecked(self.client.hotkey.mode == HotkeyMode.TOGGLE)
        self.toggle_action.toggled.connect(self._on_toggle_mode)
        self.menu.addAction(self.toggle_action)

        self.menu.addSeparator()

        # Parent the action to the menu AND keep a Python reference. Without an
        # owner, the QAction is garbage-collected when start() returns and the
        # underlying C++ object is destroyed — silently dropping "Quit" (and its
        # separator) from the menu. The two actions above survived only because
        # they're held as instance attributes.
        self.quit_action = QAction("Quit", self.menu)
        self.quit_action.triggered.connect(self._on_quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.show()
        logger.info("System tray icon ready")

    def update_recording_state(self, active: bool) -> None:
        """Reflect a hotkey state change in the tray label, tooltip, and icon."""
        if self.state_action is not None:
            self.state_action.setText("Recording: ON  ●" if active else "Recording: OFF")
        if self.tray is not None:
            self.tray.setToolTip(
                "Wispr Dragon — recording" if active else "Wispr Dragon — idle"
            )
        self._refresh_icon(active)

    def stop(self) -> None:
        """Hide and release the tray icon."""
        if self.tray is not None:
            self.tray.hide()
            self.tray = None

    # --- internals --------------------------------------------------------

    def _refresh_icon(self, active: bool) -> None:
        # Built-in Qt pixmaps as placeholders until a real Wispr Dragon icon
        # is added — Play = recording, Pause = idle.
        app = QApplication.instance()
        if app is None or self.tray is None:
            return
        which = (
            QStyle.StandardPixmap.SP_MediaPlay if active
            else QStyle.StandardPixmap.SP_MediaPause
        )
        self.tray.setIcon(app.style().standardIcon(which))

    def _on_toggle_mode(self, checked: bool) -> None:
        mode = HotkeyMode.TOGGLE if checked else HotkeyMode.PTT
        self.client.set_mode(mode)

    def _on_quit(self) -> None:
        logger.info("Quit requested from system tray")
        self.client.stop()
        app = QApplication.instance()
        if app is not None:
            app.quit()
