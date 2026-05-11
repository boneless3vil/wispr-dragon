"""PyQt6 correction window for reviewing and fixing transcriptions."""

import logging
import sys
from typing import Callable, Optional

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


def _check_pyqt6():
    try:
        from PyQt6.QtWidgets import QApplication
        return True
    except ImportError:
        return False


class CorrectionWindow:
    """Popup window for correcting transcription errors.

    Mimics Dragon NaturallySpeaking correction dialog:
    - Shows the original transcription
    - Offers suggestions from the user dictionary
    - Allows manual correction
    - Option to always apply a correction automatically
    """

    def __init__(self, dictionary, on_correction: Optional[Callable] = None):
        self.dictionary = dictionary
        self.on_correction = on_correction
        self._app = None
        self._window = None

    def show(self, original_text: str, context: str = "") -> Optional[str]:
        """Show the correction window and return the corrected text.

        Args:
            original_text: The text to correct
            context: Surrounding context for display

        Returns:
            Corrected text, or None if cancelled
        """
        if not _check_pyqt6():
            logger.warning("PyQt6 not available, falling back to terminal correction")
            return self._terminal_fallback(original_text)

        from PyQt6.QtWidgets import (
            QApplication, QDialog, QVBoxLayout, QHBoxLayout,
            QLabel, QLineEdit, QListWidget, QPushButton, QCheckBox,
        )
        from PyQt6.QtCore import Qt

        if self._app is None:
            self._app = QApplication.instance() or QApplication(sys.argv)

        dialog = QDialog()
        dialog.setWindowTitle("Wispr-Dragon Correction")
        dialog.setMinimumWidth(450)
        dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(dialog)

        # Context display
        if context:
            ctx_label = QLabel(f"Context: ...{context}...")
            ctx_label.setWordWrap(True)
            layout.addWidget(ctx_label)

        # Original text
        layout.addWidget(QLabel("Original:"))
        original_label = QLabel(f'"{original_text}"')
        original_label.setStyleSheet("font-weight: bold; color: #cc0000;")
        layout.addWidget(original_label)

        # Correction input
        layout.addWidget(QLabel("Correction:"))
        correction_input = QLineEdit()
        correction_input.setText(original_text)
        correction_input.selectAll()
        layout.addWidget(correction_input)

        # Suggestions list
        layout.addWidget(QLabel("Suggestions:"))
        suggestions_list = QListWidget()
        suggestions = self._get_suggestions(original_text)
        for suggestion in suggestions:
            suggestions_list.addItem(suggestion)
        layout.addWidget(suggestions_list)

        def on_suggestion_clicked(item):
            correction_input.setText(item.text())

        suggestions_list.itemClicked.connect(on_suggestion_clicked)

        # Always apply checkbox
        always_apply = QCheckBox("Always apply this correction automatically")
        layout.addWidget(always_apply)

        # Buttons
        button_layout = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        skip_btn = QPushButton("Skip")
        cancel_btn = QPushButton("Cancel")
        button_layout.addWidget(apply_btn)
        button_layout.addWidget(skip_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        result = {"text": None, "always": False}

        def on_apply():
            result["text"] = correction_input.text()
            result["always"] = always_apply.isChecked()
            dialog.accept()

        def on_skip():
            result["text"] = original_text
            dialog.accept()

        apply_btn.clicked.connect(on_apply)
        skip_btn.clicked.connect(on_skip)
        cancel_btn.clicked.connect(dialog.reject)
        correction_input.returnPressed.connect(on_apply)

        if dialog.exec() == QDialog.DialogCode.Accepted and result["text"]:
            corrected = result["text"]
            if corrected != original_text:
                if result["always"]:
                    # Set frequency high to auto-apply
                    for _ in range(self.dictionary.correction.auto_apply_threshold
                                   if hasattr(self.dictionary, 'correction')
                                   else 3):
                        self.dictionary.add_correction(original_text, corrected)
                else:
                    self.dictionary.add_correction(original_text, corrected)
                if self.on_correction:
                    self.on_correction(original_text, corrected)
            return corrected
        return None

    def _get_suggestions(self, text: str) -> list[str]:
        """Generate correction suggestions from the dictionary."""
        suggestions = []

        # Check existing corrections for this text
        existing = self.dictionary.get_correction(text)
        if existing:
            suggestions.append(existing)

        # Fuzzy match against known correct words
        if self.dictionary.custom_words:
            matches = process.extract(
                text, self.dictionary.custom_words,
                scorer=fuzz.ratio, limit=5, score_cutoff=60,
            )
            for match_text, score, _ in matches:
                if match_text not in suggestions:
                    suggestions.append(match_text)

        # Add the original as last option
        if text not in suggestions:
            suggestions.append(text)

        return suggestions

    def _terminal_fallback(self, original_text: str) -> Optional[str]:
        """Simple terminal-based correction when PyQt6 is unavailable."""
        print(f'\nOriginal: "{original_text}"')
        suggestions = self._get_suggestions(original_text)
        for i, s in enumerate(suggestions, 1):
            print(f"  {i}. {s}")
        print("  0. Cancel")

        try:
            choice = input("Select or type correction: ").strip()
            if choice == "0":
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(suggestions):
                corrected = suggestions[int(choice) - 1]
            else:
                corrected = choice

            if corrected != original_text:
                self.dictionary.add_correction(original_text, corrected)
                if self.on_correction:
                    self.on_correction(original_text, corrected)
            return corrected
        except (EOFError, KeyboardInterrupt):
            return None
