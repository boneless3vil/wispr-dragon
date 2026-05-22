"""Floating dictation window — core UI for voice-to-text input.

Mimics Dragon 16.1's dictation box: minimal, always-on-top, shows live transcription.
Styled with a clean light theme — white surface, blue accent.
"""

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

# Accent colors — also used at runtime to recolor the record-state dot.
_ACCENT = "#2563eb"   # blue: recording
_IDLE = "#9ca3af"     # gray: idle

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
    background: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
}
QPushButton#postButton:hover {
    background: #1d4ed8;
    border: 1px solid #1d4ed8;
}
QPushButton#postButton:pressed {
    background: #1e40af;
    border: 1px solid #1e40af;
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

    def __init__(self, config, user_dir: Path, on_text_ready=None, parent=None):
        """Initialize dictation box.

        Args:
            config: Config object with audio/engine settings
            user_dir: User config directory (~/.wispr_dragon)
            on_text_ready: Callback when text is ready to post (receives text)
            parent: Parent widget (usually None for top-level window)
        """
        super().__init__()
        self.config = config
        self.user_dir = user_dir
        self.on_text_ready = on_text_ready
        self.is_recording = False
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

        # Keyboard shortcuts
        self.window.keyPressEvent = self._on_key_press

        # Route worker-thread emits through Qt's queued connection so all widget
        # mutation happens on the GUI thread.
        self.transcription_updated.connect(self._apply_transcription_update)
        self.status_message_changed.connect(self._apply_status_message)

    def _set_recording_state(self, recording: bool) -> None:
        """Update the header dot + label to reflect recording state."""
        self.is_recording = recording
        if recording:
            self.status_dot.setStyleSheet(f"color: {_ACCENT};")
            self.status_text.setText("Recording")
        else:
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

    @pyqtSlot(str)
    def _apply_status_message(self, msg: str) -> None:
        self.status_bar.showMessage(msg)

    def _on_key_press(self, event):
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key.Key_Return:
            self.post_text()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_recording()
        elif event.key() == Qt.Key.Key_L and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.clear_text()
        else:
            event.ignore()

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
        import html

        if final:
            logger.info("Slot received final: %r (total len %d)", final[:80], len(self.final_text) + len(final))
            # Each `final` carries one completed VAD segment. Append to the
            # running transcript so multi-segment dictation accumulates.
            if self.final_text:
                self.final_text = f"{self.final_text} {final}"
            else:
                self.final_text = final
            self.live_text = ""
        else:
            self.live_text = live

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

    def post_text(self):
        """Post the transcribed text to the active window."""
        text = self.final_text.strip()
        if not text:
            self.status_bar.showMessage("No text to post")
            return

        # TODO: Check for command matches + show confirmation if needed
        # For now, just post the text
        if self.on_text_ready:
            self.on_text_ready(text)

        self.status_bar.showMessage("✓ Text posted")
        self._timer.stop()
        self._set_recording_state(False)
        self.window.close()

    def clear_text(self):
        """Clear the current text and optionally restart recording."""
        self.final_text = ""
        self.live_text = ""
        self.text_display.clear()
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
