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
