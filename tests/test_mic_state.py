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
