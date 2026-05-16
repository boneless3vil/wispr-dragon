"""Floating dictation window — core UI for voice-to-text input.

Mimics Dragon 16.1's dictation box: minimal, always-on-top, shows live transcription.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _check_pyqt6():
    """Check if PyQt6 is available."""
    try:
        from PyQt6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


class DictationBox:
    """Main window for voice dictation.

    Features:
    - Live transcription display
    - Post, Clear, Cancel buttons
    - Keyboard shortcuts (Enter, Escape, Ctrl+L)
    - Always-on-top floating window
    - Command detection with confirmation dialogs
    - Audio and transcription on separate threads
    """

    def __init__(self, config, user_dir: Path, on_text_ready=None, parent=None):
        """Initialize dictation box.

        Args:
            config: Config object with audio/engine settings
            user_dir: User config directory (~/.wispr_dragon)
            on_text_ready: Callback when text is ready to post (receives text)
            parent: Parent widget (usually None for top-level window)
        """
        if not _check_pyqt6():
            logger.error("PyQt6 not available. Install with: pip install PyQt6")
            raise ImportError("PyQt6 is required for UI mode")

        from PyQt6.QtWidgets import (
            QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QTextEdit, QPushButton, QLabel, QStatusBar
        )
        from PyQt6.QtCore import Qt, QSize
        from PyQt6.QtGui import QFont

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

    def _on_key_press(self, event):
        """Handle keyboard shortcuts."""
        from PyQt6.QtCore import Qt

        if event.key() == Qt.Key.Key_Return:
            self.post_text()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_recording()
        elif event.key() == Qt.Key.Key_L and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.clear_text()
        else:
            event.ignore()

    def update_transcription(self, live: str, final: str = None):
        """Update the transcription display.

        Args:
            live: Current live transcription (hypothesis)
            final: Final transcription (if segment completed)
        """
        if final:
            self.final_text = final
            self.live_text = ""
        else:
            self.live_text = live

        # Display format: final text + grayed live text
        display = self.final_text
        if self.live_text:
            display += f"\n\n<i style='color: gray;'>{self.live_text}</i>"

        self.text_display.setText(display)
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
