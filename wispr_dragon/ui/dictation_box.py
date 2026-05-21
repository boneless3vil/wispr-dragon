"""Floating dictation window — core UI for voice-to-text input.

Mimics Dragon 16.1's dictation box: minimal, always-on-top, shows live transcription.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)


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

        # Create main window
        self.window = QMainWindow(parent)
        self.window.setWindowTitle("Wispr Dragon Dictation")
        self.window.setGeometry(100, 100, 500, 250)
        self.window.setWindowFlags(
            self.window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
        )

        # Create central widget and layout
        central = QWidget()
        layout = QVBoxLayout()

        # Title
        title = QLabel("🎤 Dictation Active")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Transcription display (read-only)
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setMinimumHeight(100)
        self.text_display.setPlaceholderText("Start speaking...")
        layout.addWidget(self.text_display)

        # Button layout
        button_layout = QHBoxLayout()

        self.post_btn = QPushButton("Post [↵]")
        self.post_btn.clicked.connect(self.post_text)
        button_layout.addWidget(self.post_btn)

        self.clear_btn = QPushButton("Clear [Ctrl+L]")
        self.clear_btn.clicked.connect(self.clear_text)
        button_layout.addWidget(self.clear_btn)

        self.cancel_btn = QPushButton("Cancel [Esc]")
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
                f"<br><br><i style='color: gray;'>"
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
        self.window.close()

    def clear_text(self):
        """Clear the current text and optionally restart recording."""
        self.final_text = ""
        self.live_text = ""
        self.text_display.clear()
        self.status_bar.showMessage("Cleared. Ready to record...")

    def cancel_recording(self):
        """Cancel recording and close window."""
        self.window.close()

    def show(self):
        """Display the dictation box and start recording."""
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.is_recording = True
        self.status_bar.showMessage("Recording... Press Escape to cancel")

    def close(self):
        """Close the dictation box."""
        self.window.close()

    def is_visible(self) -> bool:
        """Check if window is visible."""
        return self.window.isVisible()
