"""Offscreen Qt tests for the client CorrectionDialog."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wispr_dragon.client.correction_dialog import CorrectionDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_lists_synthesized_alternates_including_original(qapp):
    dlg = CorrectionDialog("there", dictionary=None)
    try:
        # homophones of "there" plus the original.
        assert "there" in dlg.alternates
        assert any(a in ("their", "they're") for a in dlg.alternates)
    finally:
        dlg.deleteLater()


def test_select_index_loads_input(qapp):
    dlg = CorrectionDialog("there", dictionary=None)
    try:
        ok = dlg.select_index(1)
        assert ok is True
        assert dlg.correction_input.text() == dlg.alternates[0]
    finally:
        dlg.deleteLater()


def test_select_index_out_of_range(qapp):
    dlg = CorrectionDialog("there", dictionary=None)
    try:
        assert dlg.select_index(99) is False
    finally:
        dlg.deleteLater()


def test_apply_returns_text_and_always_flag(qapp):
    dlg = CorrectionDialog("there", dictionary=None)
    try:
        dlg.correction_input.setText("their")
        dlg.always_apply.setChecked(True)
        dlg.apply_now()
        result = dlg.result_correction()
        assert result == ("their", True)
    finally:
        dlg.deleteLater()


def test_apply_blank_does_not_accept(qapp):
    dlg = CorrectionDialog("there", dictionary=None)
    try:
        dlg.correction_input.setText("   ")
        dlg.apply_now()
        assert dlg.result_correction() is None
    finally:
        dlg.deleteLater()


def test_result_none_before_apply(qapp):
    dlg = CorrectionDialog("there", dictionary=None)
    try:
        assert dlg.result_correction() is None
    finally:
        dlg.deleteLater()


def test_apply_without_edit_returns_the_original_verbatim(qapp):
    """Regression: .strip() turned an unedited "Hello.\n" into "Hello." — a
    bogus correction that ate the dictated newline and was learned."""
    dlg = CorrectionDialog("Hello.\n", dictionary=None)
    try:
        dlg.apply_now()
        assert dlg.result_correction() == ("Hello.\n", False)
    finally:
        dlg.deleteLater()


def test_edit_keeps_the_original_surrounding_whitespace(qapp):
    dlg = CorrectionDialog("\ntheir\n", dictionary=None)
    try:
        dlg.correction_input.setText("there")
        dlg.apply_now()
        assert dlg.result_correction() == ("\nthere\n", False)
    finally:
        dlg.deleteLater()


def test_heard_label_shows_markup_as_plain_text(qapp):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLabel

    dlg = CorrectionDialog("<b>bold</b>", dictionary=None)
    try:
        heard = [w for w in dlg.findChildren(QLabel) if "<b>bold</b>" in w.text()]
        assert heard and heard[0].textFormat() == Qt.TextFormat.PlainText
    finally:
        dlg.deleteLater()
