"""Tests for the hotkey state machine.

The pynput-backed listener can't run headlessly, but the state machine is
pure logic — autorepeat filtering, mode switching, key tracking — so it's
fully testable without any real keyboard input.
"""

from wispr_dragon.client.hotkey import HotkeyMode, HotkeyStateMachine


# --- push-to-talk ---------------------------------------------------------

def test_ptt_press_activates_release_deactivates():
    s = HotkeyStateMachine(HotkeyMode.PTT)
    assert s.active is False
    assert s.on_press() is True
    assert s.active is True
    assert s.on_release() is False
    assert s.active is False


def test_ptt_ignores_os_autorepeat():
    s = HotkeyStateMachine(HotkeyMode.PTT)
    s.on_press()
    # OS repeats fire on_press while the key is held. Active stays True;
    # nothing else should toggle.
    assert s.on_press() is True
    assert s.on_press() is True
    assert s.active is True
    assert s.key_down is True
    s.on_release()
    assert s.active is False


def test_ptt_release_without_press_is_a_noop():
    s = HotkeyStateMachine(HotkeyMode.PTT)
    assert s.on_release() is False
    assert s.active is False
    assert s.key_down is False


# --- toggle ---------------------------------------------------------------

def test_toggle_flips_active_on_each_press():
    s = HotkeyStateMachine(HotkeyMode.TOGGLE)
    assert s.on_press() is True    # first press: start
    s.on_release()
    assert s.active is True        # release in toggle mode does nothing
    assert s.on_press() is False   # second press: stop
    s.on_release()
    assert s.active is False
    assert s.on_press() is True    # third press: start again
    s.on_release()
    assert s.active is True


def test_toggle_ignores_autorepeat():
    # Holding the key in toggle mode must not rapidly flip the state.
    s = HotkeyStateMachine(HotkeyMode.TOGGLE)
    s.on_press()      # active=True
    s.on_press()      # autorepeat, should be ignored
    s.on_press()      # autorepeat, should be ignored
    assert s.active is True
    s.on_release()
    s.on_press()      # real second press
    assert s.active is False


# --- mode switching -------------------------------------------------------

def test_switching_to_ptt_while_idle_keeps_idle():
    s = HotkeyStateMachine(HotkeyMode.TOGGLE)
    s.set_mode(HotkeyMode.PTT)
    assert s.active is False
    assert s.mode == HotkeyMode.PTT


def test_switching_to_ptt_clears_a_stuck_toggle_active():
    # A user could end up with active=True in TOGGLE mode (they pressed once
    # and walked away). Switching to PTT must not leave the mic stuck on.
    s = HotkeyStateMachine(HotkeyMode.TOGGLE)
    s.on_press()
    s.on_release()
    assert s.active is True       # toggle leaves it on after release
    s.set_mode(HotkeyMode.PTT)
    assert s.active is False
    assert s.mode == HotkeyMode.PTT


def test_switching_to_ptt_while_key_held_leaves_active_alone():
    # If the user is mid-hold and we flip modes, don't drop the active state
    # they're actively driving.
    s = HotkeyStateMachine(HotkeyMode.TOGGLE)
    s.on_press()  # active=True, key_down=True
    s.set_mode(HotkeyMode.PTT)
    assert s.active is True
    # And a release in PTT correctly deactivates.
    s.on_release()
    assert s.active is False


def test_switching_to_toggle_preserves_state():
    s = HotkeyStateMachine(HotkeyMode.PTT)
    s.on_press()                  # PTT active=True (held)
    s.set_mode(HotkeyMode.TOGGLE)
    assert s.active is True       # stays on
    s.on_release()
    assert s.active is True       # toggle ignores release
