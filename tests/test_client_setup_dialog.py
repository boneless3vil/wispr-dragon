"""Offscreen Qt tests for the client SetupDialog.

Real QDialog (not mocks), headless via QT_QPA_PLATFORM=offscreen; skipped if
PyQt6 is unavailable. Mirrors tests/test_client_tray.py.
"""

from __future__ import annotations

import gc
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from wispr_dragon.client.setup_dialog import SetupDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _save_btn(dlg):
    return dlg.buttons.button(QDialogButtonBox.StandardButton.Save)


def test_save_disabled_when_key_blank(qapp):
    dlg = SetupDialog({"server_url": "ws://localhost:8765", "api_key": ""})
    try:
        assert _save_btn(dlg).isEnabled() is False
    finally:
        dlg.deleteLater()


def test_save_enabled_when_valid(qapp):
    dlg = SetupDialog({"server_url": "ws://localhost:8765", "api_key": "abc"})
    try:
        assert _save_btn(dlg).isEnabled() is True
    finally:
        dlg.deleteLater()


def test_invalid_url_disables_save_and_shows_error(qapp):
    dlg = SetupDialog({"server_url": "ws://localhost:8765", "api_key": "abc"})
    try:
        dlg.url_input.setText("http://nope")
        assert _save_btn(dlg).isEnabled() is False
        assert "ws://" in dlg.error_label.text()
    finally:
        dlg.deleteLater()


def test_on_save_trims_and_returns_config(qapp):
    dlg = SetupDialog({"server_url": "", "api_key": ""})
    try:
        dlg.url_input.setText("  ws://host:8765  ")
        dlg.key_input.setText("  secret  ")
        dlg._on_save()
        result = dlg.result_config()
        assert result is not None
        assert result["server_url"] == "ws://host:8765"
        assert result["api_key"] == "secret"
    finally:
        dlg.deleteLater()


def test_result_none_before_save(qapp):
    dlg = SetupDialog({"server_url": "ws://h:1", "api_key": "k"})
    try:
        assert dlg.result_config() is None
    finally:
        dlg.deleteLater()


def test_show_key_toggle_changes_echo_mode(qapp):
    from PyQt6.QtWidgets import QLineEdit

    dlg = SetupDialog({"server_url": "ws://h:1", "api_key": "k"})
    try:
        assert dlg.key_input.echoMode() == QLineEdit.EchoMode.Password
        dlg.show_key.setChecked(True)
        assert dlg.key_input.echoMode() == QLineEdit.EchoMode.Normal
    finally:
        dlg.deleteLater()


def test_dialog_survives_gc(qapp):
    """Widgets must remain valid after a GC pass (the QAction-lifetime lesson)."""
    dlg = SetupDialog({"server_url": "ws://h:1", "api_key": "k"})
    try:
        gc.collect()
        # Accessing children must not raise on a deleted C++ object.
        assert _save_btn(dlg).isEnabled() is True
    finally:
        dlg.deleteLater()
