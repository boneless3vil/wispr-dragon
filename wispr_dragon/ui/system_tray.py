"""System tray icon for Wispr Dragon UI."""

import logging
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class SystemTray(QObject):
    """Minimal system tray icon with minimize/restore and mode toggle.

    Threading: ``set_mic_state`` may be called from any thread (sleep/wake mode
    changes fire on the transcription worker). It only emits a signal; the tray
    widgets are touched in the connected slot, which Qt runs on the GUI thread
    (this object's thread) via a queued connection.
    """

    _mic_state_requested = pyqtSignal(object)  # MicState

    def __init__(
        self,
        dictation_box,
        on_quit: Optional[Callable] = None,
        on_toggle: Optional[Callable] = None,
        on_open_browser: Optional[Callable] = None,
        toggle_on_click: bool = True,
    ):
        """Initialize system tray.

        Args:
            dictation_box: DictationBox instance to control
            on_quit: Callback when user selects Quit
            on_toggle: Callback when user toggles recording on/off (the menu
                item, and a left-click on the icon if ``toggle_on_click``)
            on_open_browser: Callback to open the Commands & Vocabulary
                browser. Wired by the caller (e.g. UIController) which owns the
                user_dir and UserDictionary and constructs the MacroEditor.
            toggle_on_click: Left-clicking the icon toggles recording. The
                caller turns this off where a click opens the menu instead.
        """
        super().__init__()
        self.dictation_box = dictation_box
        self.on_quit = on_quit
        self.on_toggle = on_toggle
        self.on_open_browser = on_open_browser
        self.toggle_on_click = toggle_on_click
        self.tray_widget = None
        self.menu = None
        self.toggle_action = None
        self._mic_state_requested.connect(self._apply_mic_state)

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
        self.tray_widget.setToolTip(f"Wispr Dragon{self._click_hint()}")
        self.tray_widget.activated.connect(self._on_activated)

        # Create context menu
        self.menu = QMenu()

        # Show/Hide action
        show_action = QAction("Show Dictation Box", self.menu)
        show_action.triggered.connect(self._on_show_clicked)
        self.menu.addAction(show_action)

        # Recording toggle — label tracks the mic state (see set_mic_state).
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

    def _click_hint(self) -> str:
        return " (click to toggle)" if self.toggle_on_click else ""

    def set_recording_state(self, is_recording: bool) -> None:
        """Update recording state display in tray menu (binary on/off).

        Retained for callers that only track recording on/off; prefer
        set_mic_state() for the full Dragon-style OFF/STANDBY/HOT model.
        GUI thread only.

        Args:
            is_recording: True if recording active
        """
        if self.toggle_action:
            state_text = "Recording: ON 🎙️" if is_recording else "Recording: OFF 🔇"
            self.toggle_action.setText(state_text)

    def set_mic_state(self, state) -> None:
        """Thread-safe: update the tray for a mic state (OFF/STANDBY/HOT).

        Callable from any thread; the update is applied on the GUI thread.

        Args:
            state: a MicState value.
        """
        self._mic_state_requested.emit(state)

    @pyqtSlot(object)
    def _apply_mic_state(self, state) -> None:
        """Slot — runs on the GUI thread. Sets the menu label, tooltip and icon."""
        from .mic_state import MicState

        hint = self._click_hint()
        label, tooltip = {
            MicState.HOT: ("Recording: ON 🎙️", f"Wispr Dragon — listening{hint}"),
            MicState.STANDBY: ("Standby 💤 (say 'wake up')", "Wispr Dragon — asleep; say 'wake up'"),
            MicState.OFF: ("Recording: OFF 🔇", f"Wispr Dragon — mic off{hint}"),
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

    @staticmethod
    def _invoke(what: str, callback: Callable) -> None:
        """Run a menu callback, logging instead of raising.

        These run as Qt slots, and PyQt6 aborts the whole process when an
        exception escapes a slot — one broken menu item must not kill the app.
        """
        try:
            callback()
        except Exception:
            logger.exception("Tray action %r failed", what)

    def _on_activated(self, reason) -> None:
        """Icon clicked: a plain (left) click toggles recording."""
        from PyQt6.QtWidgets import QSystemTrayIcon

        if self.toggle_on_click and reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_toggle_recording()

    def _on_show_clicked(self) -> None:
        """Handle Show Dictation Box action."""
        if self.dictation_box:
            self._invoke("show", self.dictation_box.restore)

    def _on_toggle_recording(self) -> None:
        """Handle toggle recording action.

        Invokes the on_toggle callback (wired by UIController) so the menu
        item actually starts/stops recording rather than only logging.
        """
        logger.debug("Toggle recording requested")
        if self.on_toggle:
            self._invoke("toggle", self.on_toggle)

    def _on_open_browser(self) -> None:
        """Handle Commands & Vocabulary action."""
        logger.debug("Open Commands & Vocabulary browser requested")
        if self.on_open_browser:
            self._invoke("browser", self.on_open_browser)

    def _on_quit_clicked(self) -> None:
        """Handle Quit action."""
        if self.on_quit:
            self.on_quit()
