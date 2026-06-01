"""Regression tests for the Windows client system-tray menu (client/tray.py).

These use a *real* QApplication + QMenu rather than mocks, because the bug
being guarded against is a Qt C++ object-lifetime issue that a Mock cannot
reproduce: a QAction created as a bare local with no parent gets garbage-
collected when ``start()`` returns, silently dropping "Quit" from the menu.

Run headless via the offscreen Qt platform; skipped entirely if PyQt6 or a
usable QSystemTrayIcon environment isn't present.
"""

from __future__ import annotations

import gc
import os
from unittest.mock import Mock

import pytest

# Force a headless Qt platform before QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from wispr_dragon.client.hotkey import HotkeyMode  # noqa: E402
from wispr_dragon.client.tray import TrayApp  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """A single QApplication for the module (Qt allows only one)."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def fake_client():
    """Minimal stand-in for WisprDragonClient — TrayApp only reads hotkey.mode."""
    client = Mock()
    client.hotkey.mode = HotkeyMode.PTT
    return client


def _menu_texts(tray: TrayApp) -> list[str]:
    """Visible (non-separator) labels in the tray context menu, in order."""
    return [a.text() for a in tray.menu.actions() if not a.isSeparator()]


def test_menu_has_all_three_actions(qapp, fake_client):
    """Recording / Toggle / Quit must all be present after start()."""
    tray = TrayApp(fake_client)
    tray.start()
    try:
        texts = _menu_texts(tray)
        assert any("Recording" in t for t in texts)
        assert any("Toggle" in t for t in texts)
        assert any(t == "Quit" for t in texts)
    finally:
        tray.stop()


def test_quit_action_survives_garbage_collection(qapp, fake_client):
    """The exact regression: Quit must not vanish after a GC pass.

    Previously the Quit QAction was a bare local with no Qt parent, so it was
    collected once start() returned and the C++ object was destroyed — Quit
    (and its separator) silently disappeared from the menu.
    """
    tray = TrayApp(fake_client)
    tray.start()
    try:
        gc.collect()  # would have reaped the orphaned QAction
        assert "Quit" in _menu_texts(tray)
        # And it's actually wired to the handler.
        assert tray.quit_action is not None
    finally:
        tray.stop()


def test_quit_action_triggers_client_stop(qapp, fake_client):
    """Triggering Quit tears the client down (stop) and is held on the menu."""
    tray = TrayApp(fake_client)
    tray.start()
    try:
        assert tray.quit_action is not None
        tray.quit_action.trigger()
        fake_client.stop.assert_called_once()
    finally:
        tray.stop()
