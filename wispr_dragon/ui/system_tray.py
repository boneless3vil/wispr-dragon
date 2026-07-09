"""System tray icon for Wispr Dragon UI."""

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SystemTray:
    """Minimal system tray icon with minimize/restore and mode toggle."""

    def __init__(
        self,
        dictation_box,
        on_quit: Optional[Callable] = None,
        on_toggle: Optional[Callable] = None,
        on_open_browser: Optional[Callable] = None,
    ):
        """Initialize system tray.

        Args:
            dictation_box: DictationBox instance to control
            on_quit: Callback when user selects Quit
            on_toggle: Callback when user toggles recording on/off
            on_open_browser: Callback to open the Commands & Vocabulary
                browser. Wired by the caller (e.g. UIController) which owns the
                user_dir and UserDictionary and constructs the MacroEditor.
        """
        self.dictation_box = dictation_box
        self.on_quit = on_quit
        self.on_toggle = on_toggle
        self.on_open_browser = on_open_browser
        self.tray_widget = None
        self.menu = None

    def setup(self) -> bool:
        """Initialize tray icon and menu.

        Returns:
            True if setup successful, False if PyQt6 unavailable
        """
        try:
            from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
            from PyQt6.QtGui import QAction
        except ImportError:
            logger.warning("PyQt6 not available, skipping system tray")
            return False

        app = QApplication.instance()
        if not app:
            return False

        # Create tray icon. Start with the OFF artwork; set_mic_state() swaps in
        # the red HOT icon once capture begins. Without an icon the tray shows a
        # blank/placeholder square on most desktops.
        self.tray_widget = QSystemTrayIcon(app)
        from ..icons import mic_off_icon
        off = mic_off_icon()
        if off is not None:
            self.tray_widget.setIcon(off)
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

        # Commands & Vocabulary browser (Dragon-equivalent command browser)
        browser_action = QAction("Commands & Vocabulary…", self.menu)
        browser_action.triggered.connect(self._on_open_browser)
        self.menu.addAction(browser_action)

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
        """Update recording state display in tray menu (binary on/off).

        Retained for callers that only track recording on/off; prefer
        set_mic_state() for the full Dragon-style OFF/STANDBY/HOT model.

        Args:
            is_recording: True if recording active
        """
        if self.toggle_action:
            state_text = "Recording: ON 🎙️" if is_recording else "Recording: OFF 🔇"
            self.toggle_action.setText(state_text)

    def set_mic_state(self, state) -> None:
        """Update the tray for a Dragon-style mic state (OFF/STANDBY/HOT).

        Args:
            state: a MicState value. Sets the menu label and tooltip; the
                indicator is text/emoji since the tray icon is glyph-based.
        """
        from .mic_state import MicState

        label, tooltip = {
            MicState.HOT: ("Recording: ON 🎙️", "Wispr Dragon — listening (click to toggle)"),
            MicState.STANDBY: ("Standby 💤 (say 'wake up')", "Wispr Dragon — asleep; say 'wake up'"),
            MicState.OFF: ("Recording: OFF 🔇", "Wispr Dragon — mic off (click to toggle)"),
        }.get(state, ("Recording: OFF 🔇", "Wispr Dragon"))

        if self.toggle_action:
            self.toggle_action.setText(label)
        if self.tray_widget:
            self.tray_widget.setToolTip(tooltip)
            # Swap the tray artwork: red mic when HOT, black otherwise (OFF and
            # STANDBY both show the off icon — the label/tooltip carry the nuance).
            from ..icons import icon_for_mic_state
            icon = icon_for_mic_state(state)
            if icon is not None:
                self.tray_widget.setIcon(icon)

    def _on_show_clicked(self) -> None:
        """Handle Show Dictation Box action."""
        if self.dictation_box:
            self.dictation_box.show()
            self.dictation_box.raise_()

    def _on_toggle_recording(self) -> None:
        """Handle toggle recording action.

        Invokes the on_toggle callback (wired by UIController) so the menu
        item actually starts/stops recording rather than only logging.
        """
        logger.debug("Toggle recording requested")
        if self.on_toggle:
            self.on_toggle()

    def _on_open_browser(self) -> None:
        """Handle Commands & Vocabulary action."""
        logger.debug("Open Commands & Vocabulary browser requested")
        if self.on_open_browser:
            self.on_open_browser()

    def _on_quit_clicked(self) -> None:
        """Handle Quit action."""
        if self.on_quit:
            self.on_quit()
