"""Unit tests for WisprDragonClient (client/app.py) — no Qt, no network.

Collaborators (injector, websocket client, audio capture, tray) are replaced
by small fakes so each test pins one behaviour: config IO, queue gating,
transcript handling, and how the session survives auth / audio failures.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import logging.handlers
import sys
import threading
from pathlib import Path

import pytest

import wispr_dragon.client.app as app_mod
from wispr_dragon.client.app import (
    AUDIO_QUEUE_MAXSIZE,
    WisprDragonClient,
    _echo_transcript,
    configure_logging,
    default_config_dir,
    install_excepthooks,
)


# --- fakes ------------------------------------------------------------------

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


class FakeWS:
    """Stand-in for WebSocketClient as the app sees it."""

    def __init__(self, connected=True, utterance=True, auth_fail=False):
        self.is_connected = connected
        self._utterance = utterance
        self._auth_fail = auth_fail
        self.auth_failed = False
        self.started = asyncio.Event()
        self._stopped = False
        self.disconnect_delay = 0.0

        self.retries = 0

    def supports(self, feature):
        return self._utterance and feature == "utterance"

    def retry_now(self):
        self.retries += 1

    async def run(self, queue):
        self.started.set()
        if self._auth_fail:
            self.auth_failed = True
            return
        while not self._stopped:
            await asyncio.sleep(0.01)

    def stop(self):
        self._stopped = True

    async def disconnect(self):
        self._stopped = True
        await asyncio.sleep(self.disconnect_delay)


class FakeCapture:
    """Audio capture whose start() fails ``failures`` times, then runs."""

    def __init__(self, failures=0):
        self.failures = failures
        self.starts = 0
        self.error = None
        self._running = False
        self.paused = True

    async def start(self, queue):
        self.starts += 1
        if self.starts <= self.failures:
            self.error = "device unplugged"
            return
        self.error = None
        self._running = True
        while self._running:
            await asyncio.sleep(0.01)

    def stop(self):
        self._running = False

    def set_paused(self, paused):
        self.paused = paused


@pytest.fixture
def client(tmp_path):
    c = WisprDragonClient(config_path=tmp_path / "config.json", no_tray=True)
    c.injector = FakeInjector()
    return c


async def _wait_until(predicate, timeout=2.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def _notifications(c):
    seen = []
    c._notify = lambda title, message: seen.append((title, message))
    return seen


# --- config paths + IO (item 12) --------------------------------------------

def test_default_config_dir_per_platform(tmp_path):
    home = tmp_path
    assert default_config_dir("win32", {}, home) == home / "AppData" / "Local" / "WisprDragon"
    assert default_config_dir("darwin", {}, home) == (
        home / "Library" / "Application Support" / "WisprDragon"
    )
    assert default_config_dir("linux", {}, home) == home / ".config" / "wispr_dragon"
    xdg = str(tmp_path / "xdg")
    assert default_config_dir("linux", {"XDG_CONFIG_HOME": xdg}, home) == Path(xdg) / "wispr_dragon"
    # A relative XDG path is invalid per the spec and ignored.
    assert default_config_dir("linux", {"XDG_CONFIG_HOME": "rel"}, home) == (
        home / ".config" / "wispr_dragon"
    )


def test_config_with_utf8_bom_loads(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"api_key": "k", "server_url": "ws://h:1"}).encode())
    c = WisprDragonClient(config_path=path, no_tray=True)
    assert c.config["api_key"] == "k"


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_unreadable_config_is_backed_up_before_defaults_are_used(tmp_path, content):
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")
    c = WisprDragonClient(config_path=path, no_tray=True)
    assert c.config["api_key"] == ""  # defaults
    assert (tmp_path / "config.json.bad").read_text(encoding="utf-8") == content
    c._save_config()  # e.g. first-run setup overwrites the original...
    assert (tmp_path / "config.json.bad").read_text(encoding="utf-8") == content  # ...but it's safe


def test_save_config_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    c = WisprDragonClient(config_path=path, no_tray=True)
    c.config["api_key"] = "first"
    c._save_config()
    assert json.loads(path.read_text(encoding="utf-8"))["api_key"] == "first"

    def exploding_dump(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(app_mod.json, "dump", exploding_dump)
    c.config["api_key"] = "second"
    with pytest.raises(OSError):
        c._save_config()
    # The old file is intact and no temp file is left behind.
    assert json.loads(path.read_text(encoding="utf-8"))["api_key"] == "first"
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_try_save_config_reports_instead_of_raising(client, monkeypatch):
    seen = _notifications(client)

    def deny(*a, **k):
        raise PermissionError("locked")

    monkeypatch.setattr(client, "_save_config", deny)
    assert client._try_save_config() is False
    assert seen and "locked" in seen[0][1]


# --- transcripts + injection (items 1, 10) -----------------------------------

def test_no_stray_space_after_a_dictated_newline(client):
    client._on_transcript("Hello.\n")
    client._on_transcript("World")
    assert client.injector.injected == ["Hello.\n", "World "]
    assert client._last_injection_text == "World"
    assert client._last_injection_len == len("World ")


def test_control_characters_never_reach_the_injector(client):
    client._on_transcript("a\x1bb\r\nc")
    assert client.injector.injected == ["ab\nc "]
    client._on_transcript("\x07")
    assert len(client.injector.injected) == 1


def test_correct_that_is_deferred_out_of_the_listener_task(client):
    """Regression: the dialog was opened synchronously inside the websocket
    listen() Task, and its nested Qt loop wedged every other task."""

    async def scenario():
        client._loop = asyncio.get_running_loop()
        calls = []
        client._open_correction = lambda: calls.append("open")
        client._on_transcript("correct that")
        synchronous = list(calls)
        await asyncio.sleep(0)  # let the loop run the scheduled callback
        return synchronous, calls

    synchronous, calls = asyncio.run(scenario())
    assert synchronous == [], "must not open the dialog inside the calling Task"
    assert calls == ["open"]
    assert client.injector.injected == [], "the command itself is not typed"


class FakeDialog:
    def __init__(self):
        self.text = None
        self.selected = []
        self.applied = 0
        self.rejected = 0
        outer = self

        class _Input:
            def setText(self, text):
                outer.text = text

        self.correction_input = _Input()

    def select_index(self, n):
        self.selected.append(n)
        return n <= 3

    def apply_now(self):
        self.applied += 1

    def reject(self):
        self.rejected += 1


def test_speech_drives_an_open_correction_dialog(client):
    dlg = FakeDialog()
    client._correction_dialog = dlg
    client._on_transcript("choose two")
    assert dlg.selected == [2] and dlg.applied == 1
    client._on_transcript("choose nine")  # out of range: select fails, no apply
    assert dlg.applied == 1
    client._on_transcript("Their.")
    assert dlg.text == "Their."
    client._on_transcript("correct that")  # already open: ignored
    assert dlg.text == "Their."
    client._on_transcript("cancel")
    assert dlg.rejected == 1
    assert client.injector.injected == [], "nothing typed while correcting"


class FinishedDialog:
    def __init__(self, result):
        self._result = result

    def result_correction(self):
        return self._result

    def deleteLater(self):
        pass


def test_unchanged_correction_is_a_noop(client):
    client._last_injection_len = 8
    client._on_correction_finished(FinishedDialog(("Hello.\n", False)), "Hello.\n", 1)
    assert client.injector.replaced == []


def test_correction_keeps_newline_and_learns_stripped_text(client):
    learned = []
    client._learn_correction = lambda *args: learned.append(args)
    client._last_injection_text = "their\n"
    client._last_injection_len = 6
    client._on_correction_finished(FinishedDialog(("there\n", True)), "their\n", 1)
    assert client.injector.replaced == [(6, "there\n")]
    assert client._last_injection_len == len("there\n")
    assert learned == [("their", "there", True)]


def test_cancelled_correction_does_nothing(client):
    client._on_correction_finished(FinishedDialog(("x", False)), "y", 0)
    assert client.injector.replaced == []


# --- queue gating (item 7) ---------------------------------------------------

def test_audio_queue_is_bounded():
    assert 0 < AUDIO_QUEUE_MAXSIZE <= 200


def test_frames_are_not_queued_while_disconnected(client):
    async def scenario():
        client.audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
        client.audio_capture = FakeCapture()
        client.ws_client = None
        client._apply_active(True)
        client._apply_active(False)
        offline = client.audio_queue.qsize()
        client.ws_client = FakeWS(connected=False)
        client._apply_active(True)
        client._apply_active(False)
        down = client.audio_queue.qsize()
        client.ws_client = FakeWS(connected=True)
        client._apply_active(True)
        client._apply_active(False)
        up = [client.audio_queue.get_nowait()["type"] for _ in range(client.audio_queue.qsize())]
        return offline, down, up

    offline, down, up = asyncio.run(scenario())
    assert offline == 0 and down == 0
    assert up == ["utterance_start", "utterance_end"]


def test_full_queue_evicts_audio_never_a_control_frame(client):
    """utterance_start/end delimit the utterance; evicting one would merge or
    truncate utterances on the server. Only audio may make room."""
    start = {"type": "utterance_start", "id": "u"}
    end = {"type": "utterance_end", "id": "u"}

    async def scenario():
        client.audio_queue = asyncio.Queue(maxsize=3)
        client.ws_client = FakeWS(connected=True)
        for item in (start, b"\x01", b"\x02"):
            client.audio_queue.put_nowait(item)
        client._enqueue_control(end)
        return [client.audio_queue.get_nowait() for _ in range(3)]

    assert asyncio.run(scenario()) == [start, b"\x02", end]


def test_capture_leaves_headroom_for_control_frames():
    from wispr_dragon.client.audio_capture import CONTROL_HEADROOM, WindowsAudioCapture

    async def scenario():
        queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
        cap = WindowsAudioCapture()
        cap._queue = queue
        for _ in range(AUDIO_QUEUE_MAXSIZE * 2):
            cap._enqueue(b"\x00")
        return queue.qsize()

    assert asyncio.run(scenario()) == AUDIO_QUEUE_MAXSIZE - CONTROL_HEADROOM


# --- session resilience (items 3, 4, 13) -------------------------------------

def test_hotkey_failure_is_recorded_for_the_tray(client, monkeypatch):
    def bad_start(self):
        raise ValueError("Unknown hotkey: 'numpad_plus'")

    monkeypatch.setattr(app_mod.Hotkey, "start", bad_start)
    client.config["hotkey"] = "numpad_plus"
    client._start_hotkey()
    assert client.hotkey is None
    assert "numpad_plus" in client.hotkey_error


def test_auth_failure_idles_until_new_settings_then_reconnects(client):
    async def scenario():
        seen = _notifications(client)
        client.tray = FakeTray()  # tray mode: idle for Settings (no tray: exit)
        client._running = True
        client.audio_queue = asyncio.Queue()
        client.audio_capture = FakeCapture()
        client.ws_client = FakeWS(auth_fail=True)
        rebuilt = []

        def rebuild():
            client.ws_client = FakeWS()
            rebuilt.append(client.ws_client)

        client._build_ws_client = rebuild
        session = asyncio.create_task(client._run_session())
        await asyncio.sleep(0.3)
        idle = client.unconfigured and not session.done() and not rebuilt
        client.unconfigured = False  # what open_settings() does on Save
        reconnected = await _wait_until(lambda: rebuilt and rebuilt[0].started.is_set())
        client.stop()
        await asyncio.wait_for(session, 2)
        return idle, reconnected, seen

    idle, reconnected, seen = asyncio.run(scenario())
    assert idle, "client must stay alive (idle) after an auth rejection"
    assert reconnected, "saving settings must reconnect without a restart"
    assert [t for t, _ in seen] == ["Authentication failed"]


def test_audio_error_is_retried_not_fatal(client, monkeypatch):
    monkeypatch.setattr(app_mod, "_AUDIO_RETRY_MIN_S", 0.05)

    async def scenario():
        seen = _notifications(client)
        client._running = True
        client.audio_queue = asyncio.Queue()
        client.audio_capture = FakeCapture(failures=2)
        client.ws_client = FakeWS()
        session = asyncio.create_task(client._run_session())
        await asyncio.sleep(0.5)
        alive = not session.done()
        starts = client.audio_capture.starts
        client.stop()
        await asyncio.wait_for(session, 2)
        return alive, starts, seen

    alive, starts, seen = asyncio.run(scenario())
    assert alive, "a microphone error must not end the client"
    assert starts == 3
    assert [t for t, _ in seen] == ["Microphone unavailable"], "notified once, not per retry"


def test_shutdown_is_bounded_when_disconnect_hangs(client, monkeypatch):
    monkeypatch.setattr(app_mod, "_SHUTDOWN_DISCONNECT_S", 0.2)

    async def scenario():
        client.ws_client = FakeWS()
        client.ws_client.disconnect_delay = 30
        loop = asyncio.get_running_loop()
        started = loop.time()
        await client.shutdown()
        return loop.time() - started

    assert asyncio.run(scenario()) < 2


def test_busy_status_notifies_once_per_episode(client):
    seen = _notifications(client)
    for status in ("connected", "busy", "disconnected", "reconnecting (1)", "connected", "busy"):
        client._on_status(status)
    client._on_status("ready")
    client._on_status("busy")
    assert [t for t, _ in seen] == ["Server busy", "Server busy"]


class FakeTray:
    def __init__(self):
        self.status = None
        self.notes = []

    def set_status(self, status):
        self.status = status

    def notify(self, title, message):
        self.notes.append(title)

    def update_recording_state(self, active):
        pass


def test_busy_tooltip_clears_on_an_unrelated_failure(client):
    client.tray = FakeTray()
    client._on_status("busy")
    client._on_status("reconnecting (1)")
    assert "busy" in client.tray.status
    client._on_status("connect_failed")  # server now unreachable, not busy
    client._on_status("reconnecting (2)")
    assert client.tray.status == "not connected - retrying"


def test_hotkey_while_offline_notifies_once_and_kicks_reconnect(client, monkeypatch):
    seen = _notifications(client)
    clock = {"t": 1000.0}
    monkeypatch.setattr(app_mod, "_monotonic", lambda: clock["t"])

    async def scenario():
        client.audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
        client.audio_capture = FakeCapture()
        client.ws_client = FakeWS(connected=False)
        for _ in range(3):     # t=1000 kicks; 1001 and 1002 are rate-limited
            client._apply_active(True)
            client._apply_active(False)
            clock["t"] += 1
        clock["t"] += 10       # t=1013: limit expired -> second kick
        client._apply_active(True)
        client._apply_active(False)
        client._on_status("ready")  # link back: the next outage notifies again
        client._apply_active(True)  # t=1013 again: rate-limited, but notifies

    asyncio.run(scenario())
    assert client.ws_client.retries == 2, "kicks are rate-limited (>= 5 s apart)"
    assert [t for t, _ in seen] == ["Not connected", "Not connected"]


def test_no_tray_auth_failure_exits_non_zero(client):
    async def scenario():
        client._running = True
        client.audio_queue = asyncio.Queue()
        client.audio_capture = FakeCapture()
        client.ws_client = FakeWS(auth_fail=True)
        await asyncio.wait_for(client._run_session(), 2)

    asyncio.run(scenario())  # returns instead of idling forever
    assert client.exit_code == app_mod.EXIT_AUTH_FAILED
    assert client._running is False


def test_run_gates_capture_on_the_server_link(client, monkeypatch):
    made = {}

    class RecordingCapture(FakeCapture):
        def __init__(self, **kwargs):
            super().__init__()
            made.update(kwargs)

    async def no_session():
        pass

    monkeypatch.setattr(app_mod, "WindowsAudioCapture", RecordingCapture)
    monkeypatch.setattr(app_mod.Hotkey, "start", lambda self: None)
    client.config.update({"server_url": "ws://127.0.0.1:1", "api_key": "k"})
    client._run_session = no_session
    asyncio.run(client.run())
    assert made["gate"] == client._link_up


def test_legacy_config_is_read_when_the_native_one_is_missing(tmp_path, monkeypatch):
    legacy = tmp_path / "AppData" / "Local" / "WisprDragon" / "config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"api_key": "old", "server_url": "ws://h:1"}), encoding="utf-8")
    native = tmp_path / ".config" / "wispr_dragon" / "config.json"
    monkeypatch.setattr(app_mod, "DEFAULT_CONFIG_PATH", native)
    monkeypatch.setattr(app_mod, "legacy_config_path", lambda: legacy)
    c = WisprDragonClient(no_tray=True)
    assert c.config["api_key"] == "old"
    c._save_config()
    assert json.loads(native.read_text(encoding="utf-8"))["api_key"] == "old"
    # An explicit --config path never falls back.
    explicit = WisprDragonClient(config_path=tmp_path / "other.json", no_tray=True)
    assert explicit.config["api_key"] == ""


def test_legacy_config_path_is_only_for_non_windows(tmp_path):
    assert app_mod.legacy_config_path("win32", tmp_path) is None
    assert app_mod.legacy_config_path("linux", tmp_path) == (
        tmp_path / "AppData" / "Local" / "WisprDragon" / "config.json"
    )


def test_refused_second_instance_logs_and_releases_client_log(tmp_path, monkeypatch):
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    old_hooks = sys.excepthook, threading.excepthook
    monkeypatch.setattr(sys, "argv", ["wispr_dragon_client", "--no-tray"])
    monkeypatch.setattr(app_mod, "acquire_single_instance", lambda: None)
    monkeypatch.setattr(app_mod, "default_config_dir", lambda: tmp_path)
    try:
        assert app_mod.main() == 3
        ours = [h for h in root.handlers
                if h not in before and isinstance(h, logging.FileHandler)]
        assert ours == [], "refused instance must not keep client.log open"
        assert "already running" in (tmp_path / "client.log").read_text(encoding="utf-8")
    finally:
        for h in [h for h in root.handlers if h not in before]:
            root.removeHandler(h)
            h.close()
        root.setLevel(level)
        sys.excepthook, threading.excepthook = old_hooks


# --- logging + crash safety (items 6, 11) ------------------------------------

def test_dictated_text_is_not_logged_at_info_or_printed(client, caplog, capsys):
    caplog.set_level(logging.INFO)
    client._on_transcript("my private dictation")
    # The former leak: a successful correction logged both texts at INFO.
    client._learn_correction = lambda *args: None
    client._last_injection_len = 6
    client._on_correction_finished(FinishedDialog(("secret fix", False)), "secret typo", 1)
    assert client.injector.replaced, "the correction path actually ran"
    assert "my private dictation" not in caplog.text
    assert "secret typo" not in caplog.text and "secret fix" not in caplog.text
    assert "my private dictation" not in capsys.readouterr().out, "no stdout echo when typing"


def test_transcripts_are_printed_with_no_inject(tmp_path, capsys):
    c = WisprDragonClient(config_path=tmp_path / "config.json", inject=False, no_tray=True)
    c._on_transcript("print me")
    assert "[TRANSCRIPT] print me" in capsys.readouterr().out


def test_echo_transcript_never_raises():
    real = sys.stdout
    try:
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        _echo_transcript("mic \U0001F3A4 arrow →")  # not encodable in cp1252
        sys.stdout = None
        _echo_transcript("windowed build has no stdout")
    finally:
        sys.stdout = real


def test_configure_logging_writes_utf8_rotating_file(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    try:
        path = configure_logging(tmp_path / "logs")
        logging.getLogger("wispr_dragon.test").warning("emoji \U0001F3A4 dash — ok")
        added = [h for h in root.handlers if h not in before]
        for h in added:
            h.flush()
        assert path == tmp_path / "logs" / "client.log"
        assert "emoji \U0001F3A4 dash — ok" in path.read_text(encoding="utf-8")
        rotating = [h for h in added if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert rotating and rotating[0].maxBytes == 1_000_000 and rotating[0].backupCount == 3
    finally:
        for h in [h for h in root.handlers if h not in before]:
            root.removeHandler(h)
            h.close()
        root.setLevel(level)


def test_excepthooks_log_instead_of_crashing(caplog):
    old_sys, old_thread = sys.excepthook, threading.excepthook
    try:
        install_excepthooks()
        with caplog.at_level(logging.CRITICAL):
            try:
                raise PermissionError("settings file locked")
            except PermissionError as e:
                sys.excepthook(type(e), e, e.__traceback__)
        assert "Unhandled exception" in caplog.text
        assert "settings file locked" in caplog.text
    finally:
        sys.excepthook, threading.excepthook = old_sys, old_thread
