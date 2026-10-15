"""The client's "correct that" flow end to end, with a real (offscreen) dialog.

The bug guarded here: the correction dialog used to be opened with
``QDialog.exec()`` from inside the websocket listen() Task. Under qasync that
nested Qt loop wedges every *other* asyncio task for good — audio capture, the
socket feeder, keepalives — and Quit then hangs holding the mic. The dialog is
now opened non-modally (``open()`` + ``finished``) from a plain loop callback.
"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from wispr_dragon.client.app import WisprDragonClient  # noqa: E402


class FakeInjector:
    available = True
    method = "paste"

    def __init__(self):
        self.injected = []
        self.replaced = []

    def inject(self, text):
        self.injected.append(text)
        return True

    def replace_last(self, old_len, text):
        self.replaced.append((old_len, text))
        return True


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    previous = app.quitOnLastWindowClosed()
    # Like the real client: closing the dialog must not quit the Qt loop.
    app.setQuitOnLastWindowClosed(False)
    yield app
    app.setQuitOnLastWindowClosed(previous)


@pytest.fixture
def client(tmp_path):
    c = WisprDragonClient(config_path=tmp_path / "config.json", no_tray=True)
    c.injector = FakeInjector()
    c._last_injection_text = "there"
    c._last_injection_len = len("there ")
    return c


def test_correction_round_trip_without_blocking(qapp, client):
    """The dialog opens without blocking; Apply backspaces and retypes."""

    async def scenario():
        client._loop = asyncio.get_running_loop()
        client._on_transcript("correct that")
        await asyncio.sleep(0)
        dlg = client._correction_dialog
        assert dlg is not None and dlg.isVisible()
        client._on_transcript("correct that")  # second trigger: no second dialog
        await asyncio.sleep(0)
        assert client._correction_dialog is dlg
        dlg.correction_input.setText("their")
        dlg.apply_now()
        return client._correction_dialog

    after = asyncio.run(scenario())
    assert after is None, "dialog released once finished"
    assert client.injector.replaced == [(len("there "), "their ")]
    assert client._last_injection_text == "their"


def test_correct_that_keeps_other_tasks_running_under_qasync(qapp, client):
    """Regression for the qasync wedge (needs qasync, as in the real client)."""
    qasync = pytest.importorskip("qasync")

    def close_any_modal():
        # Safety net: if exec() is ever reintroduced, end it so the test fails
        # on its assertions instead of hanging the suite.
        widget = QApplication.activeModalWidget()
        if widget is not None:
            widget.close()

    safety = QTimer()
    safety.setSingleShot(True)
    safety.timeout.connect(close_any_modal)

    ticks = []

    async def ticker():
        while True:
            ticks.append(1)
            await asyncio.sleep(0.02)

    async def listener():
        # Stands in for WebSocketClient.listen(): the transcript callback runs
        # inside a Task.
        client._on_transcript("correct that")
        await asyncio.sleep(0)

    async def scenario():
        client._loop = asyncio.get_running_loop()
        tick_task = asyncio.create_task(ticker())
        await asyncio.create_task(listener())
        await asyncio.sleep(0.1)
        dialog_open = client._correction_dialog is not None
        before = len(ticks)
        await asyncio.sleep(0.5)
        progressed = len(ticks) - before
        if client._correction_dialog is not None:
            client._correction_dialog.reject()
        tick_task.cancel()
        return dialog_open, progressed

    loop = qasync.QEventLoop(qapp)
    asyncio.set_event_loop(loop)
    safety.start(3000)
    try:
        with loop:
            dialog_open, progressed = loop.run_until_complete(
                asyncio.wait_for(scenario(), 10)
            )
    finally:
        safety.stop()
        asyncio.set_event_loop(None)

    assert dialog_open, "the correction dialog should be open"
    assert progressed >= 5, f"sibling task starved while the dialog was open ({progressed} ticks)"
    assert client._correction_dialog is None
    assert client.injector.replaced == [], "cancelled correction changes nothing"


def _pump(qapp, seconds):
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)


def test_correction_window_stays_on_top_and_announces_itself(qapp, client):
    from PyQt6.QtCore import Qt

    notes = []
    client._notify = lambda title, message: notes.append((title, message))
    client._open_correction()
    dlg = client._correction_dialog
    try:
        assert dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert notes and notes[0][0] == "Correction window open"
        assert "cancel" in notes[0][1]
    finally:
        dlg.reject()


def test_idle_correction_window_closes_itself(qapp, client, monkeypatch):
    """Left open, the window would swallow every later dictation."""
    import wispr_dragon.client.app as app_mod

    monkeypatch.setattr(app_mod, "_CORRECTION_IDLE_TIMEOUT_MS", 400)
    client._open_correction()
    dlg = client._correction_dialog
    assert dlg is not None
    _pump(qapp, 0.25)
    client._on_transcript("their")       # speech counts as activity: timer restarts
    _pump(qapp, 0.25)                    # 0.5 s since opening, 0.25 s idle
    assert client._correction_dialog is dlg, "activity must postpone the timeout"
    _pump(qapp, 0.6)
    assert client._correction_dialog is None, "idle dialog should have closed"
    assert client.injector.replaced == [], "a timed-out correction changes nothing"
