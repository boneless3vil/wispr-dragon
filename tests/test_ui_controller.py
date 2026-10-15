"""Regression tests for the --ui desktop path: UIController + DictationBox + tray.

These deliberately use *real* Qt objects under the offscreen platform rather
than Mocks. The tray's "Show Dictation Box" and "Commands & Vocabulary…" crashes
went unnoticed because the old tests stubbed ``raise_`` onto a Mock box and never
built the dialog. Only the engine, the VAD and the audio device are faked.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import Mock

import numpy as np
import pytest

# Force a headless Qt platform before QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QSystemTrayIcon  # noqa: E402

from wispr_dragon.config import Config  # noqa: E402
from wispr_dragon.correction.dictionary import UserDictionary  # noqa: E402
from wispr_dragon.correction.post_processor import PostProcessor  # noqa: E402
from wispr_dragon.modes.mode_manager import Mode  # noqa: E402
from wispr_dragon.ui.dictation_box import DictationBox  # noqa: E402
from wispr_dragon.ui.mic_state import MicState  # noqa: E402
from wispr_dragon.ui.system_tray import SystemTray  # noqa: E402
from wispr_dragon.ui.ui_controller import UIController  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """A single QApplication for the module (Qt allows only one)."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def controller(qapp, tmp_path, config):
    """An initialized UIController with a real box, orchestrator and dictionary."""
    from wispr_dragon.modes import command_mode

    # initialize() points the module-global command registry at user_dir;
    # put it back so later tests don't load commands from this tmp_path.
    registry_user_dir = command_mode._registry.user_dir
    dictionary = UserDictionary(path=tmp_path / "dictionary.json")
    engine = Mock()
    engine.transcribe.return_value = Mock(text="hello world")
    ctl = UIController(
        config,
        tmp_path,
        engine,
        vad=Mock(),
        post_processor=PostProcessor(dictionary),
        dictionary=dictionary,
    )
    assert ctl.initialize()
    yield ctl
    if ctl.tray is not None and ctl.tray.tray_widget is not None:
        ctl.tray.tray_widget.hide()
    ctl.dictation_box.window.close()
    command_mode._registry.user_dir = registry_user_dir
    command_mode._registry.load()


def _run_one_segment(ctl: UIController, text: str) -> None:
    """Drive the real worker loop over exactly one VAD segment, synchronously.

    The fake VAD stops the worker as it hands back the segment, so ``run()``
    transcribes it, delivers it to the controller and returns. The box lives on
    this (GUI) thread, so its signals are delivered as direct calls.
    """
    worker = ctl.transcription_worker
    ctl.engine.transcribe.return_value = Mock(text=text)
    segment = np.zeros(16000, dtype=np.float32)

    def process_chunk(_chunk):
        worker.stop()
        return segment

    worker.vad.process_chunk.side_effect = process_chunk
    worker.enqueue_chunk(np.zeros(1600, dtype=np.float32))
    worker.run()


def _menu_action(tray: SystemTray, prefix: str):
    """Find a tray menu QAction by the start of its label."""
    for action in tray.menu.actions():
        if action.text().startswith(prefix):
            return action
    raise AssertionError(f"no tray action starting with {prefix!r}")


# --------------------------------------------------------------------------- #
# Tray "Show Dictation Box"
# --------------------------------------------------------------------------- #

class TestTrayShowDictationBox:
    def test_show_restores_a_real_box(self, qapp, tmp_path):
        """DictationBox is a QObject wrapper, not a widget — no raise_() on it."""
        box = DictationBox(Config(), tmp_path)
        box.show()
        box.window.showMinimized()

        SystemTray(box)._on_show_clicked()

        assert box.window.isVisible()
        assert not box.window.isMinimized()
        box.window.close()

    def test_restore_does_not_reset_the_session(self, qapp, tmp_path):
        """Bringing a paused box forward must not restart the timer or go HOT."""
        box = DictationBox(Config(), tmp_path)
        box.show()
        box.toggle_mic()                    # paused: timer frozen
        box._paint_mic_state(MicState.OFF)  # what the controller's observer paints
        box._elapsed_seconds = 42
        box.window.showMinimized()

        SystemTray(box)._on_show_clicked()

        assert not box._timer.isActive()
        assert box._elapsed_seconds == 42
        assert box.status_text.text() == "Idle"
        box.window.close()


# --------------------------------------------------------------------------- #
# Tray "Commands & Vocabulary…"
# --------------------------------------------------------------------------- #

class TestCommandVocabBrowser:
    @pytest.fixture
    def exec_spy(self, monkeypatch):
        """Make QDialog.exec non-blocking and record the dialog it ran."""
        seen = {}

        def fake_exec(dialog):
            seen["dialog"] = dialog
            seen["parent"] = dialog.parent()
            return 0  # Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        return seen

    def test_browser_constructs_a_real_dialog_parented_to_the_box(
        self, controller, exec_spy
    ):
        controller.open_command_vocab_browser()

        assert exec_spy["parent"] is controller.dictation_box.window

    def test_browser_reloads_macros_after_it_closes(self, controller, exec_spy):
        runner = controller.macro_runner
        runner.reload_macros = Mock(wraps=runner.reload_macros)

        controller.open_command_vocab_browser()

        runner.reload_macros.assert_called_once()

    def test_tray_menu_entry_opens_the_browser(self, controller, exec_spy):
        controller._setup_tray()
        assert controller.tray is not None

        _menu_action(controller.tray, "Commands").trigger()

        assert exec_spy["parent"] is controller.dictation_box.window


# --------------------------------------------------------------------------- #
# Session config reaches the modes/macros pipeline
# --------------------------------------------------------------------------- #

class TestPipelineConfig:
    @pytest.fixture
    def config(self):
        cfg = Config()
        cfg.security.dictation_only = True  # as set by --dictation-only
        return cfg

    def test_dictation_only_flag_reaches_mode_manager(self, controller):
        assert controller.mode_mgr.is_dictation_only()

        controller.mode_mgr.process_text("switch to command mode")

        assert controller.mode_mgr.mode == Mode.DICTATION

    def test_commands_load_from_the_session_user_dir(self, controller, tmp_path):
        from wispr_dragon.modes import command_mode

        assert command_mode._registry.user_dir == tmp_path


class TestMacroDeclined:
    def test_declined_macro_text_can_be_scratched(self, controller, monkeypatch):
        """'No' types the trigger phrase as dictation; 'scratch that' must undo it."""
        from wispr_dragon.ui.confirm_command import ConfirmationDialog

        monkeypatch.setattr(ConfirmationDialog, "show_and_ask", lambda *a, **k: "no")
        controller.is_running = True
        controller._run_macro({
            "macro": {"trigger": "open browser", "action": "launch", "program": "firefox"},
            "text": "open browser",
        })
        assert controller.dictation_box.segments == ["open browser"]

        controller.mode_mgr.process_text("scratch that")

        assert controller.dictation_box.segments == []


# --------------------------------------------------------------------------- #
# Post-processing happens exactly once, mode-aware; engine gets hotwords
# --------------------------------------------------------------------------- #

class TestSinglePostProcessing:
    def test_worker_does_not_post_process_when_orchestrator_exists(self, controller):
        assert controller.orchestrator is not None
        assert controller.transcription_worker.post_processor is None

    def test_each_segment_is_post_processed_once(self, controller):
        pp = controller.post_processor
        pp.process = Mock(wraps=pp.process)
        controller.is_running = True

        _run_one_segment(controller, "hello world")

        assert pp.process.call_count == 1
        assert controller.dictation_box.segments  # the text reached the box

    def test_spelling_mode_keeps_cap_for_the_transformer(self, controller):
        """'cap a b c' spelled -> 'Abc'. Pre-formatting ate the 'cap' -> 'abc'."""
        controller.is_running = True
        controller.mode_mgr.process_text("spelling mode")
        assert controller.mode_mgr.mode == Mode.SPELLING

        _run_one_segment(controller, "cap a b c")

        assert controller.dictation_box.segments[-1] == "Abc"

    def test_engine_receives_hotwords_and_initial_prompt(self, controller):
        controller.dictionary.add_custom_word("Kubernetes")
        controller.is_running = True

        _run_one_segment(controller, "hello world")

        kwargs = controller.engine.transcribe.call_args.kwargs
        assert "Kubernetes" in kwargs["hotwords"]
        assert "Kubernetes" in kwargs["initial_prompt"]

    def test_without_orchestrator_the_controller_post_processes(self, controller):
        controller.orchestrator = None
        controller.is_running = True
        expected = controller.post_processor.process("hello world")

        controller._on_transcription(live="", final="hello world")

        assert controller.dictation_box.segments == [expected]


# --------------------------------------------------------------------------- #
# Tray is only touched on the GUI thread
# --------------------------------------------------------------------------- #

class TestTrayThreadSafety:
    def test_mic_state_from_worker_thread_is_applied_on_gui_thread(self, qapp):
        tray = SystemTray(None)
        assert tray.setup()
        try:
            tray.set_mic_state(MicState.HOT)  # GUI thread: applied immediately
            assert tray.toggle_action.text().startswith("Recording: ON")

            worker = threading.Thread(target=tray.set_mic_state, args=(MicState.STANDBY,))
            worker.start()
            worker.join()
            # Not applied on the worker thread...
            assert tray.toggle_action.text().startswith("Recording: ON")

            # ...but once the GUI thread's event loop runs.
            QCoreApplication.processEvents()
            assert tray.toggle_action.text().startswith("Standby")
        finally:
            tray.tray_widget.hide()


# --------------------------------------------------------------------------- #
# Tray toggle item + click-to-toggle
# --------------------------------------------------------------------------- #

class TestTrayToggle:
    def test_menu_toggle_pauses_and_resumes_the_mic(self, controller):
        controller.mic_state.set_capturing(True)
        controller._setup_tray()
        box = controller.dictation_box

        controller.tray.toggle_action.trigger()
        assert box._mic_paused
        assert controller.audio_worker.is_paused
        assert controller.mic_state.state == MicState.OFF

        controller.tray.toggle_action.trigger()
        assert not box._mic_paused
        assert controller.mic_state.state == MicState.HOT

    def test_left_click_toggles_the_mic(self, controller, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        controller._setup_tray()
        icon = controller.tray.tray_widget

        icon.activated.emit(QSystemTrayIcon.ActivationReason.Context)
        assert not controller.dictation_box._mic_paused  # right-click: menu only

        icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        assert controller.dictation_box._mic_paused

    def test_click_does_not_toggle_on_macos(self, controller, monkeypatch):
        """macOS opens the menu on click and also reports Trigger — don't toggle."""
        monkeypatch.setattr(sys, "platform", "darwin")
        controller._setup_tray()

        controller.tray.tray_widget.activated.emit(
            QSystemTrayIcon.ActivationReason.Trigger
        )

        assert not controller.dictation_box._mic_paused


# --------------------------------------------------------------------------- #
# Resume reflects the *current* sleep/wake mode
# --------------------------------------------------------------------------- #

class TestResumeAfterModeChangeWhilePaused:
    def test_sleep_while_paused_resumes_to_standby(self, controller):
        controller.mic_state.set_capturing(True)
        controller._toggle_mic(True)
        controller.mode_mgr.process_text("go to sleep")  # still in the pipeline

        controller._toggle_mic(False)

        assert controller.mode_mgr.mode == Mode.SLEEP
        assert controller.mic_state.state == MicState.STANDBY

    def test_wake_while_paused_resumes_to_hot(self, controller):
        controller.mic_state.set_capturing(True)
        controller.mode_mgr.process_text("go to sleep")
        assert controller.mic_state.state == MicState.STANDBY
        controller._toggle_mic(True)
        controller.mode_mgr.process_text("wake up")

        controller._toggle_mic(False)

        assert controller.mic_state.state == MicState.HOT


# --------------------------------------------------------------------------- #
# Stopped sessions drop late segments; stop() doesn't block the GUI thread
# --------------------------------------------------------------------------- #

class TestStop:
    def test_segment_after_stop_is_dropped(self, controller):
        controller.orchestrator.handle_transcript = Mock()
        controller.is_running = False

        controller._on_transcription(live="", final="press enter")

        controller.orchestrator.handle_transcript.assert_not_called()
        assert controller.dictation_box.segments == []

    def test_cancel_ends_the_session(self, controller):
        controller.is_running = True

        controller.dictation_box.cancel_recording()

        assert controller.is_running is False

    def test_stop_does_not_join_busy_worker_threads(self, controller):
        release = threading.Event()
        busy = [threading.Thread(target=release.wait, daemon=True) for _ in range(2)]
        for t in busy:
            t.start()
        controller.audio_thread, controller.transcription_thread = busy

        started = time.monotonic()
        try:
            controller.stop()
            elapsed = time.monotonic() - started
        finally:
            release.set()

        assert elapsed < 0.5

    def test_audio_thread_parks_until_stop(self, controller):
        controller.audio_worker.start_recording = Mock(return_value=True)
        controller.is_running = True
        thread = threading.Thread(target=controller._audio_thread_main, daemon=True)
        thread.start()
        time.sleep(0.05)
        assert thread.is_alive()

        controller.stop()
        thread.join(timeout=1)

        assert not thread.is_alive()
        controller.audio_worker.start_recording.assert_called_once()
