"""Tests for the OFF/STANDBY/HOT mic-state model (ui/mic_state.py).

Pure logic — no Qt. Also covers the ModeManager mode-change hook that drives it.
"""

from wispr_dragon.modes.mode_manager import Mode, ModeManager
from wispr_dragon.ui.mic_state import MicState, MicStateController


def test_starts_off():
    assert MicStateController().state == MicState.OFF


def test_capturing_on_goes_hot():
    c = MicStateController()
    c.set_capturing(True)
    assert c.state == MicState.HOT


def test_capturing_off_goes_off():
    c = MicStateController(MicState.HOT)
    c.set_capturing(False)
    assert c.state == MicState.OFF


def test_sleep_wake_toggles_standby_and_hot():
    c = MicStateController(MicState.HOT)
    c.set_asleep(True)
    assert c.state == MicState.STANDBY
    c.set_asleep(False)
    assert c.state == MicState.HOT


def test_asleep_ignored_while_off():
    c = MicStateController(MicState.OFF)
    c.set_asleep(True)
    assert c.state == MicState.OFF


def test_capturing_on_does_not_clobber_standby():
    # Toggling capture shouldn't silently wake an asleep mic.
    c = MicStateController(MicState.STANDBY)
    c.set_capturing(True)
    assert c.state == MicState.STANDBY


def test_observers_notified_on_change_only():
    c = MicStateController()
    seen = []
    c.add_observer(seen.append)
    c.set_state(MicState.HOT)
    c.set_state(MicState.HOT)  # unchanged -> no notification
    c.set_state(MicState.OFF)
    assert seen == [MicState.HOT, MicState.OFF]


def test_observer_exception_is_isolated():
    c = MicStateController()
    good = []

    def boom(_state):
        raise RuntimeError("observer blew up")

    c.add_observer(boom)
    c.add_observer(good.append)
    c.set_state(MicState.HOT)  # must not raise
    assert good == [MicState.HOT]


def test_importing_mic_state_does_not_pull_in_the_ui_stack():
    # wispr_dragon.icons imports this module; the package __init__ used to drag
    # in every dialog (and gpu_advisor via settings_dialog) along with it.
    # Subprocess so sys.modules starts clean.
    import subprocess
    import sys

    code = (
        "import sys; import wispr_dragon.ui.mic_state; "
        "heavy = [m for m in ('PyQt6.QtWidgets', 'wispr_dragon.ui.ui_controller', "
        "'wispr_dragon.ui.settings_dialog', 'wispr_dragon.engine.gpu_advisor') "
        "if m in sys.modules]; "
        "assert not heavy, heavy"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_package_exports_still_resolve_lazily():
    import pytest

    import wispr_dragon.ui as ui
    from wispr_dragon.ui.ui_controller import UIController

    assert ui.UIController is UIController
    with pytest.raises(AttributeError):
        ui.NotAThing  # noqa: B018


def test_mode_change_hook_drives_mic_state():
    # End-to-end seam: a sleep/wake utterance flips the indicator.
    c = MicStateController()
    c.set_capturing(True)
    mm = ModeManager()
    mm.set_mode_change_callback(lambda mode: c.set_asleep(mode == Mode.SLEEP))

    mm.process_text("go to sleep")
    assert c.state == MicState.STANDBY

    mm.process_text("wake up")
    assert c.state == MicState.HOT
