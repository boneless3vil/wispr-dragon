"""System tray icon for Wispr Dragon UI."""

import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SystemTray:
    """Minimal system tray icon with minimize/restore and mode toggle."""

    def __init__(self, dictation_box, on_quit: Optional[Callable] = None):
        """Initialize system tray.

        Args:
            dictation_box: DictationBox instance to control
            on_quit: Callback when user selects Quit
        """
        self.dictation_box = dictation_box
        self.on_quit = on_quit
        self.tray_widget = None
        self.menu = None

    def setup(self) -> bool:
        """Initialize tray icon and menu.

        Returns:
            True if setup successful, False if PyQt6 unavailable
        """
        try:
            from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
            from PyQt6.QtGui import QIcon, QAction
            from PyQt6.QtCore import Qt
        except ImportError:
            logger.warning("PyQt6 not available, skipping system tray")
            return False

        app = QApplication.instance()
        if not app:
            return False

        # Create tray icon (use a simple emoji or fallback text)
        self.tray_widget = QSystemTrayIcon(app)
        self.tray_widget.setToolTip("Wispr Dragon — Click to toggle dictation")

        # Create context menu
        self.menu = QMenu()

        # Show/Hide action
        show_action = QAction("Show Dictation Box", self.menu)
        show_action.triggered.connect(self._on_show_clicked)
        self.menu.addAction(show_action)

        # Recording state toggle (placeholder — actual state management in UIController)
        self.toggle_action = QAction("Recording: ON", self.menu)
        self.toggle_action.triggered.connect(self._on_toggle_recording)
        self.menu.addAction(self.toggle_action)

        self.menu.addSeparator()

        # Quit action
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self._on_quit_clicked)
        self.menu.addAction(quit_action)

        self.tray_widget.setContextMenu(self.menu)

        # Show tray icon
        self.tray_widget.show()
        logger.info("System tray icon initialized")
        return True

    def set_recording_state(self, is_recording: bool) -> None:
        """Update recording state display in tray menu.

        Args:
            is_recording: True if recording active
        """
        if self.toggle_action:
            state_text = "Recording: ON 🎙️" if is_recording else "Recording: OFF 🔇"
            self.toggle_action.setText(state_text)

    def _on_show_clicked(self) -> None:
        """Handle Show Dictation Box action."""
        if self.dictation_box:
            self.dictation_box.show()
            self.dictation_box.raise_()

    def _on_toggle_recording(self) -> None:
        """Handle toggle recording action (placeholder)."""
        logger.debug("Toggle recording requested")

    def _on_quit_clicked(self) -> None:
        """Handle Quit action."""
        if self.on_quit:
            self.on_quit()
