"""Client-side correction dialog ("Correct that").

Shows the mis-recognized text, a numbered list of synthesized alternates, and
a freehand field. The user picks a numbered row (by click or — wired by the
caller — by voice "choose N"), or types a correction. "Always apply" learns it.

Follows the lightweight QDialog pattern of setup_dialog.py. Imported only on
the Qt/tray path. Alternate synthesis is delegated to the pure
``correction.alternates`` module; this is just the view.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
)

from wispr_dragon.correction.alternates import synthesize_alternates

logger = logging.getLogger(__name__)


class CorrectionDialog(QDialog):
    """Correction dialog, shown non-blocking. Result via :meth:`result_correction`.

    It is not modal: the client shows it with ``open()`` and reacts to
    ``finished``, never ``exec()`` — a nested Qt loop inside an asyncio Task
    wedges qasync (see client/app.py). It stays on top so it can't end up
    hidden behind the app being dictated into while it captures speech::

        dlg = CorrectionDialog(original, dictionary)
        dlg.finished.connect(lambda code: code and use(dlg.result_correction()))
        dlg.open()
    """

    def __init__(self, original_text: str, dictionary=None, parent=None):
        super().__init__(parent)
        self._original = original_text
        self._result: tuple[str, bool] | None = None

        self.setWindowTitle("Wispr Dragon — Correct that")
        # Windows' foreground lock can refuse to activate a window from a
        # background process; staying on top at least keeps it visible.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Heard:"))
        heard = QLabel(f'"{original_text}"')
        # Dictated text is data, not markup: without this, QLabel auto-detects
        # rich text and a transcript like "<b>x</b>" would render as HTML.
        heard.setTextFormat(Qt.TextFormat.PlainText)
        heard.setStyleSheet("font-weight: bold; color: #c0392b;")
        heard.setWordWrap(True)
        layout.addWidget(heard)

        layout.addWidget(QLabel("Correction:"))
        self.correction_input = QLineEdit(original_text)
        self.correction_input.selectAll()
        layout.addWidget(self.correction_input)

        # Numbered alternates. Display "1. text" so a spoken "choose 1" maps to
        # the visible number; selection logic uses the row index.
        self.alternates = synthesize_alternates(original_text, dictionary=dictionary)
        layout.addWidget(QLabel("Alternatives (say “choose N”):"))
        self.list_widget = QListWidget()
        for i, alt in enumerate(self.alternates, 1):
            self.list_widget.addItem(f"{i}. {alt}")
        self.list_widget.itemClicked.connect(self._on_row_clicked)
        layout.addWidget(self.list_widget)

        self.always_apply = QCheckBox("Always apply this correction automatically")
        layout.addWidget(self.always_apply)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._on_apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.correction_input.returnPressed.connect(self._on_apply)

    def result_correction(self) -> tuple[str, bool] | None:
        """(corrected_text, always_apply) if applied, else None."""
        return self._result

    # --- selection API (used by click and by voice "choose N") ------------

    def select_index(self, one_based: int) -> bool:
        """Select alternate by 1-based number; load it into the input."""
        idx = one_based - 1
        if 0 <= idx < len(self.alternates):
            self.correction_input.setText(self.alternates[idx])
            self.list_widget.setCurrentRow(idx)
            return True
        return False

    def apply_now(self) -> None:
        """Programmatic Apply (e.g. after a voice selection)."""
        self._on_apply()

    # --- internals --------------------------------------------------------

    def _on_row_clicked(self, item) -> None:
        self.select_index(self.list_widget.row(item) + 1)

    def _on_apply(self) -> None:
        text = self.correction_input.text().strip()
        if not text:
            return
        original = self._original
        core = original.strip()
        if text == core:
            # Unchanged. Report the original verbatim so the caller sees a
            # no-op; stripping it (e.g. a dictated trailing newline) used to
            # turn Apply-without-edit into a bogus correction.
            self._result = (original, self.always_apply.isChecked())
        else:
            # Keep the whitespace around the original (e.g. "\n" from a "new
            # line" command) — the single-line input can't show or edit it,
            # and the replacement must not swallow it.
            lead = original[: len(original) - len(original.lstrip())]
            trail = original[len(original.rstrip()):] if core else ""
            self._result = (lead + text + trail, self.always_apply.isChecked())
        self.accept()
