"""Floating dictation window — core UI for voice-to-text input.

Mimics Dragon 16.1's dictation box: minimal, always-on-top, shows live transcription.
Styled with a clean light theme — white surface, blue accent.
"""

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

# Accent colors — also used at runtime to recolor the mic-state dot.
_ACCENT = "#436547"   # sage green: HOT (recording)
_IDLE = "#9ca3af"     # gray: OFF (idle)
_STANDBY = "#d97706"  # amber: STANDBY (asleep — "wake up" to resume)

# Clean light theme, applied as a Qt style sheet on the window so it overrides
# the OS default widget palette. Keep selectors object-name scoped so the
# theme doesn't leak into child dialogs.
_STYLE_SHEET = """
QWidget#dictationRoot {
    background: #ffffff;
}
QLabel {
    color: #1f2937;
}
QLabel#statusText {
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusDot {
    font-size: 15px;
}
QLabel#timerLabel {
    color: #6b7280;
    font-size: 12px;
}
QLabel#hintLabel {
    color: #b45309;
    font-size: 11px;
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 6px;
    padding: 5px 8px;
}
QTextEdit#transcript {
    background: #f9fafb;
    color: #1f2937;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 8px;
    font-size: 13px;
}
QPushButton {
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 600;
    background: #f3f4f6;
    color: #374151;
}
QPushButton:hover {
    background: #e5e7eb;
}
QPushButton:pressed {
    background: #d1d5db;
}
QPushButton#postButton {
    background: #436547;
    border: 1px solid #436547;
    color: #ffffff;
}
QPushButton#postButton:hover {
    background: #39563c;
    border: 1px solid #39563c;
}
QPushButton#postButton:pressed {
    background: #2f4732;
    border: 1px solid #2f4732;
}
QStatusBar {
    color: #6b7280;
    font-size: 11px;
}
"""


class DictationBox(QObject):
    """Main window for voice dictation.

    Features:
    - Live transcription display
    - Post, Clear, Cancel buttons
    - Keyboard shortcuts (Enter, Escape, Ctrl+L)
    - Always-on-top floating window
    - Command detection with confirmation dialogs
    - Audio and transcription on separate threads
    """

    # Cross-thread signals: worker threads emit these; the connected slots run on
    # the GUI thread (queued connection) so widget mutation is thread-safe.
    transcription_updated = pyqtSignal(str, str)  # live, final (empty string = no final)
    status_message_changed = pyqtSignal(str)
    segment_pop_requested = pyqtSignal()  # "scratch that" -> drop the last segment
    # Deferred GUI-thread action requested from a worker thread. payload depends on
    # the action: "correct" -> ignored (operates on the last segment);
    # "macro" -> dict {"macro": ..., "text": ...}. Connected by UIController.
    ui_action_requested = pyqtSignal(str, object)
    mic_state_changed = pyqtSignal(object)  # MicState — repaint the dot on GUI thread

    def __init__(self, config, user_dir: Path, on_text_ready=None, parent=None,
                 on_toggle_mic=None):
        """Initialize dictation box.

        Args:
            config: Config object with audio/engine settings
            user_dir: User config directory (~/.wispr_dragon)
            on_text_ready: Callback when text is ready to post (receives text)
            parent: Parent widget (usually None for top-level window)
            on_toggle_mic: Callback when the Mic button toggles capture
                (receives paused: bool). Wired by UIController to gate audio.
        """
        super().__init__()
        self.config = config
        self.user_dir = user_dir
        self.on_text_ready = on_text_ready
        self.on_toggle_mic = on_toggle_mic
        self._mic_paused = False
        self.is_recording = False
        # Completed VAD segments accumulate here. final_text is their " "-join;
        # tracking them as a list lets "scratch that" drop the last one and
        # "correct that" replace it.
        self.segments: list[str] = []
        self.final_text = ""
        self.live_text = ""

        # Elapsed-time counter for the header timer.
        self._elapsed_seconds = 0
        self._timer = QTimer()
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        # Create main window
        self.window = QMainWindow(parent)
        self.window.setWindowTitle("Wispr Dragon Dictation")
        self.window.setGeometry(100, 100, 500, 260)
        self.window.setWindowFlags(
            self.window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )
        self.window.setStyleSheet(_STYLE_SHEET)

        # Window/taskbar icon — starts OFF; _paint_mic_state swaps to the red HOT
        # mic while recording so the taskbar mirrors the live indicator.
        from .icons import mic_off_icon
        _win_icon = mic_off_icon()
        if _win_icon is not None:
            self.window.setWindowIcon(_win_icon)

        # Create central widget and layout
        central = QWidget()
        central.setObjectName("dictationRoot")
        layout = QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # Header row: record-state dot + label on the left, elapsed timer right.
        header = QHBoxLayout()
        header.setSpacing(6)

        self.status_dot = QLabel("●")  # ●
        self.status_dot.setObjectName("statusDot")
        header.addWidget(self.status_dot)

        self.status_text = QLabel("Idle")
        self.status_text.setObjectName("statusText")
        header.addWidget(self.status_text)

        header.addStretch()

        self.timer_label = QLabel("0:00")
        self.timer_label.setObjectName("timerLabel")
        header.addWidget(self.timer_label)

        layout.addLayout(header)
        self._set_recording_state(False)

        # Backend hint — hidden unless UIController sets it (e.g. to warn that
        # the xdotool backend can't reach native Windows apps).
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("hintLabel")
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(False)
        layout.addWidget(self.hint_label)

        # Transcription display (read-only)
        self.text_display = QTextEdit()
        self.text_display.setObjectName("transcript")
        self.text_display.setReadOnly(True)
        self.text_display.setMinimumHeight(100)
        self.text_display.setPlaceholderText("Start speaking...")
        layout.addWidget(self.text_display)

        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        self.mic_btn = QPushButton("Pause Mic")
        self.mic_btn.setObjectName("micButton")
        self.mic_btn.clicked.connect(self.toggle_mic)
        button_layout.addWidget(self.mic_btn)

        self.post_btn = QPushButton("Post  ↵")
        self.post_btn.setObjectName("postButton")
        self.post_btn.clicked.connect(self.post_text)
        button_layout.addWidget(self.post_btn)

        self.clear_btn = QPushButton("Clear  Ctrl+L")
        self.clear_btn.clicked.connect(self.clear_text)
        button_layout.addWidget(self.clear_btn)

        self.cancel_btn = QPushButton("Cancel  Esc")
        self.cancel_btn.clicked.connect(self.cancel_recording)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

        # Status bar
        self.status_bar = self.window.statusBar()
        self.status_bar.showMessage("Ready to record...")

        central.setLayout(layout)
        self.window.setCentralWidget(central)

        # Keyboard shortcuts. Use window-scoped QShortcuts (default
        # WindowShortcut context) rather than overriding keyPressEvent: an
        # override only fires when the QMainWindow itself has focus, so Enter/Esc
        # were swallowed whenever a button or the transcript held focus.
        for seq, slot in (
            (QKeySequence(Qt.Key.Key_Return), self.post_text),
            (QKeySequence(Qt.Key.Key_Enter), self.post_text),   # numpad Enter
            (QKeySequence(Qt.Key.Key_Escape), self.cancel_recording),
            (QKeySequence("Ctrl+L"), self.clear_text),
        ):
            QShortcut(seq, self.window).activated.connect(slot)

        # Route worker-thread emits through Qt's queued connection so all widget
        # mutation happens on the GUI thread.
        self.transcription_updated.connect(self._apply_transcription_update)
        self.status_message_changed.connect(self._apply_status_message)
        self.segment_pop_requested.connect(self._pop_last_segment)
        self.mic_state_changed.connect(self._apply_mic_state)
        # Deferred actions are dispatched through this QObject (GUI thread) so the
        # worker-thread emit is delivered via a queued connection. The actual
        # handler is supplied by UIController via set_ui_action_handler().
        self._ui_action_handler = None
        self.ui_action_requested.connect(self._dispatch_ui_action)

    def _set_recording_state(self, recording: bool) -> None:
        """Update the header dot + label for the binary recording on/off case.

        Thin wrapper over the three-state mic indicator: recording maps to HOT,
        not-recording to OFF. STANDBY is reached only via set_mic_state().
        """
        from .mic_state import MicState
        self._paint_mic_state(MicState.HOT if recording else MicState.OFF)

    def set_mic_state(self, state) -> None:
        """Thread-safe: update the mic-state indicator (OFF/STANDBY/HOT).

        Callable from any thread (mode changes fire on the worker thread); the
        repaint is marshaled to the GUI thread via a queued signal.
        """
        self.mic_state_changed.emit(state)

    @pyqtSlot(object)
    def _apply_mic_state(self, state) -> None:
        """Slot — runs on the GUI thread."""
        self._paint_mic_state(state)

    def _paint_mic_state(self, state) -> None:
        """Recolor the dot + label for the given MicState (GUI thread)."""
        from .mic_state import MicState
        from .icons import icon_for_mic_state
        self.is_recording = state != MicState.OFF
        # Mirror the state in the window/taskbar icon (red mic = HOT).
        _icon = icon_for_mic_state(state)
        if _icon is not None:
            self.window.setWindowIcon(_icon)
        if state == MicState.HOT:
            self.status_dot.setStyleSheet(f"color: {_ACCENT};")
            self.status_text.setText("Recording")
        elif state == MicState.STANDBY:
            self.status_dot.setStyleSheet(f"color: {_STANDBY};")
            self.status_text.setText("Standby")
        else:  # OFF
            self.status_dot.setStyleSheet(f"color: {_IDLE};")
            self.status_text.setText("Idle")

    def _tick(self) -> None:
        """Advance the elapsed-time display by one second."""
        self._elapsed_seconds += 1
        minutes, seconds = divmod(self._elapsed_seconds, 60)
        self.timer_label.setText(f"{minutes}:{seconds:02d}")

    def show_status(self, msg: str) -> None:
        """Thread-safe status bar update — callable from any thread."""
        self.status_message_changed.emit(msg)

    def set_ui_action_handler(self, handler) -> None:
        """Register the callback that handles deferred UI actions.

        Invoked on the GUI thread (via the queued ui_action_requested signal)
        with (action: str, payload). UIController supplies it so QDialogs are
        only ever constructed on the GUI thread.
        """
        self._ui_action_handler = handler

    @pyqtSlot(str, object)
    def _dispatch_ui_action(self, action: str, payload) -> None:
        """Slot — runs on the GUI thread regardless of emitter thread."""
        if self._ui_action_handler:
            self._ui_action_handler(action, payload)

    def toggle_mic(self) -> None:
        """Pause/resume audio capture without ending the session (Mic button)."""
        self._mic_paused = not self._mic_paused
        self.mic_btn.setText("Resume Mic" if self._mic_paused else "Pause Mic")
        # Freeze the elapsed counter while paused so the timer reflects active
        # dictation time, not wall-clock — resuming continues from where it left
        # off. The mic-state dot is repainted by UIController via the observer.
        if self._mic_paused:
            self._timer.stop()
        else:
            self._timer.start()
        if self.on_toggle_mic:
            self.on_toggle_mic(self._mic_paused)
        self.status_bar.showMessage("Mic paused" if self._mic_paused else "Mic live")

    def set_backend_hint(self, message: str) -> None:
        """Show (or clear) a persistent hint line under the header.

        Used by UIController to warn, e.g., that the xdotool backend can't reach
        native Windows apps. Empty message hides the line.
        """
        if message:
            self.hint_label.setText(message)
            self.hint_label.setVisible(True)
        else:
            self.hint_label.clear()
            self.hint_label.setVisible(False)

    @pyqtSlot(str)
    def _apply_status_message(self, msg: str) -> None:
        self.status_bar.showMessage(msg)

    def update_transcription(self, live: str, final: Optional[str] = None):
        """Thread-safe entry point — emits a signal that runs on the GUI thread.

        Args:
            live: Current live transcription (hypothesis)
            final: Final transcription (if segment completed)
        """
        self.transcription_updated.emit(live or "", final or "")

    @pyqtSlot(str, str)
    def _apply_transcription_update(self, live: str, final: str):
        """Slot — runs on the GUI thread regardless of emitter thread."""
        if final:
            logger.info("Slot received final: %r (total len %d)", final[:80], len(self.final_text) + len(final))
            # Each `final` carries one completed VAD segment. Append to the
            # running transcript so multi-segment dictation accumulates.
            self.segments.append(final)
            self.final_text = " ".join(self.segments)
            self.live_text = ""
        else:
            self.live_text = live

        self._render()

    def _render(self) -> None:
        """Repaint the transcript display from segments + live hypothesis."""
        import html

        # Display format: final text + grayed live text. Escape user content so
        # transcribed angle brackets etc. render literally rather than as tags.
        display = html.escape(self.final_text).replace("\n", "<br>")
        if self.live_text:
            display += (
                f"<br><br><i style='color: #6b7280;'>"
                f"{html.escape(self.live_text)}</i>"
            )

        self.text_display.setHtml(display)
        self.status_bar.showMessage(f"Recording... ({len(self.final_text)} chars)")

    def remove_last_segment(self) -> None:
        """Thread-safe: drop the most recent segment (handles 'scratch that')."""
        self.segment_pop_requested.emit()

    @pyqtSlot()
    def _pop_last_segment(self) -> None:
        """Slot — runs on the GUI thread. Remove the last accepted segment."""
        if self.segments:
            self.segments.pop()
            self.final_text = " ".join(self.segments)
            self.live_text = ""
            self._render()
            self.status_bar.showMessage("Scratched last phrase")

    def last_segment(self) -> str:
        """Return the most recent segment text, or '' if none."""
        return self.segments[-1] if self.segments else ""

    def replace_last_segment(self, text: str) -> None:
        """Replace the most recent segment (handles an applied correction).

        Safe to call from the GUI thread only (correction runs there).
        """
        if self.segments:
            self.segments[-1] = text
            self.final_text = " ".join(self.segments)
            self._render()

    def post_text(self):
        """Post the transcribed text to the active window."""
        text = self.final_text.strip()
        if not text:
            self.status_bar.showMessage("No text to post")
            return

        # Commands ("scratch that", "correct that", macros, mode switches) are
        # handled upstream by the orchestrator as they're spoken, so Post only
        # ever sees finalized dictation text.
        if self.on_text_ready:
            self.on_text_ready(text)

        self.status_bar.showMessage("✓ Text posted")
        self._timer.stop()
        self._set_recording_state(False)
        self.window.close()

    def clear_text(self):
        """Clear the current text and optionally restart recording."""
        self.segments = []
        self.final_text = ""
        self.live_text = ""
        self.text_display.clear()
        # Clear starts a fresh dictation, so reset the elapsed counter too.
        self._elapsed_seconds = 0
        self.timer_label.setText("0:00")
        self.status_bar.showMessage("Cleared. Ready to record...")

    def cancel_recording(self):
        """Cancel recording and close window."""
        self._timer.stop()
        self._set_recording_state(False)
        self.window.close()

    def show(self):
        """Display the dictation box and start recording."""
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self._elapsed_seconds = 0
        self.timer_label.setText("0:00")
        self._timer.start()
        self._set_recording_state(True)
        self.status_bar.showMessage("Recording... Press Escape to cancel")

    def close(self):
        """Close the dictation box."""
        self._timer.stop()
        self._set_recording_state(False)
        self.window.close()

    def is_visible(self) -> bool:
        """Check if window is visible."""
        return self.window.isVisible()
