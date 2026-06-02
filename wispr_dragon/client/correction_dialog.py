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
    """Modal correction dialog. Result via :meth:`result_correction`.

    Usage::

        dlg = CorrectionDialog(original, dictionary)
        if dlg.exec():
            new_text, always = dlg.result_correction()
    """

    def __init__(self, original_text: str, dictionary=None, parent=None):
        super().__init__(parent)
        self._original = original_text
        self._result: tuple[str, bool] | None = None

        self.setWindowTitle("Wispr Dragon — Correct that")
        self.setModal(True)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Heard:"))
        heard = QLabel(f'"{original_text}"')
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
        self._result = (text, self.always_apply.isChecked())
        self.accept()
