"""Main client application for Wispr Dragon."""

import asyncio
import contextlib
import json
import logging
import logging.handlers
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from wispr_dragon.client.audio_capture import CONTROL_HEADROOM, WindowsAudioCapture
from wispr_dragon.client.correction_commands import is_correct_trigger, parse_selection
from wispr_dragon.client.hotkey import Hotkey, HotkeyMode
from wispr_dragon.client.websocket_client import WebSocketClient
from wispr_dragon.client.windows_injector import WindowsTextInjector, sanitize_text

# 30 ms of int16 mono silence at 16 kHz, used to flush the server's VAD when
# the hotkey releases so the last word of a phrase doesn't get buffered.
_SILENCE_FRAME = b"\x00\x00" * 480
_FLUSH_FRAMES = 33  # ~1 second — well past the VAD's silence threshold

# Frames buffered between the mic and the socket: 100 x 30 ms = 3 s. Bounded so
# a stalled connection can't grow memory without limit (it was ~115 MB/h with
# toggle on during an outage) and so old speech isn't typed out minutes later.
AUDIO_QUEUE_MAXSIZE = 100

# Reopen a failed microphone stream with capped backoff (seconds).
_AUDIO_RETRY_MIN_S = 2
_AUDIO_RETRY_MAX_S = 30
# A capture run that lasted this long counts as "worked"; the next failure is
# reported again and the retry delay starts over.
_AUDIO_HEALTHY_S = 10

# Bound on the final socket close at shutdown, so Quit can't hang on a dead network.
_SHUTDOWN_DISCONNECT_S = 3

# An open correction dialog captures all dictation; close it after this long
# without speech or edits so it can't silently swallow what follows.
_CORRECTION_IDLE_TIMEOUT_MS = 45_000

# Pressing the hotkey while disconnected cuts the reconnect backoff short — at
# most this often, so a stuck key or rapid presses can't hammer the server.
_RETRY_KICK_MIN_S = 5.0

# main()'s exit code when --no-tray hits an auth rejection (nothing to idle for).
EXIT_AUTH_FAILED = 4

_monotonic = time.monotonic  # indirection so tests can drive the clock

logger = logging.getLogger(__name__)


def default_config_dir(
    platform: Optional[str] = None,
    env: Optional[dict] = None,
    home: Optional[Path] = None,
) -> Path:
    """Per-user directory for the client's config.json and client.log.

    * Windows: ``%USERPROFILE%\\AppData\\Local\\WisprDragon`` (unchanged — the
      installed client already keeps its config there).
    * macOS:   ``~/Library/Application Support/WisprDragon``
    * Linux:   ``$XDG_CONFIG_HOME/wispr_dragon`` (default ``~/.config/wispr_dragon``)

    Arguments exist for tests; the defaults describe the running machine.
    """
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform == "win32":
        return home / "AppData" / "Local" / "WisprDragon"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "WisprDragon"
    xdg = env.get("XDG_CONFIG_HOME", "")
    # Per the XDG spec, a relative path is invalid and must be ignored.
    base = Path(xdg) if xdg and os.path.isabs(xdg) else home / ".config"
    return base / "wispr_dragon"


DEFAULT_CONFIG_PATH = default_config_dir() / "config.json"
LOG_FILENAME = "client.log"


def legacy_config_path(platform: Optional[str] = None, home: Optional[Path] = None) -> Optional[Path]:
    """Where older clients kept config.json on *every* OS (the Windows path).

    Read once on Linux/macOS when the platform-native file doesn't exist yet;
    the next save writes the native path. None on Windows (same path anyway).
    """
    if (platform or sys.platform) == "win32":
        return None
    return (home or Path.home()) / "AppData" / "Local" / "WisprDragon" / "config.json"

_DEFAULT_CONFIG = {
    "server_url": "ws://localhost:8765",
    "api_key": "",
    "sample_rate": 16000,
    "device": None,
    "mode": "ptt",
    "hotkey": "ctrl_r",
    "inject_method": "paste",
}

# Loopback port used purely as a single-instance lock. A second client is
# actively harmful: the server accepts one connection, so the loser sits in a
# reconnect storm, and *both* instances hold a global hotkey listener and the
# microphone. Binding a port (rather than writing a lock file) means the OS
# reclaims the lock when the process dies — no stale state to clean up.
_SINGLE_INSTANCE_PORT = 47653


def acquire_single_instance(port: int = _SINGLE_INSTANCE_PORT):
    """Return a bound socket acting as the instance lock, or None if one exists.

    The caller must keep the returned socket alive for the process lifetime.
    SO_REUSEADDR is deliberately NOT set — we want the second bind to fail.
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None


def needs_setup(config: dict) -> bool:
    """True when the client isn't ready to connect and should run first-run setup.

    Keys off empty/missing required fields (``api_key``, ``server_url``) rather
    than a missing file or a dedicated flag — this survives partial hand-edits
    and needs no config-schema addition. Pure: no Qt, no IO.
    """
    return not config.get("api_key") or not config.get("server_url")


def validate_setup(server_url: str, api_key: str) -> tuple[bool, str]:
    """Validate setup-dialog input. Returns (ok, error_message).

    Pure helper carrying the dialog's validation weight so it tests without a
    display. Accepts only ``ws://``/``wss://`` URLs with a host; rejects blank
    keys. ``error_message`` is "" when ok.
    """
    from urllib.parse import urlparse

    url = (server_url or "").strip()
    key = (api_key or "").strip()
    if not key:
        return False, "API key is required."
    if not url:
        return False, "Server URL is required."
    parsed = urlparse(url)
    if parsed.scheme not in ("ws", "wss"):
        return False, "Server URL must start with ws:// or wss://"
    if not parsed.netloc:
        return False, "Server URL must include a host, e.g. ws://192.168.1.10:8765"
    return True, ""


async def call_outside_task(fn: Callable, *args):
    """Run ``fn(*args)`` as a plain event-loop callback and await its result.

    Qt modal dialogs (``QDialog.exec()``) spin a nested event loop. Under qasync,
    doing that from *inside* an asyncio Task wedges every other Task for good:
    while the nested loop runs, this Task is still the loop's "current task",
    so asyncio refuses to step any other one (audio capture, the websocket
    feeder/listener, keepalives) — and Quit then hangs with the mic held. Run
    from a callback, there is no current task, and siblings keep running while
    the dialog is up. The awaiting Task simply resumes with the result.
    """
    loop = asyncio.get_running_loop()
    fut = loop.create_future()

    def _invoke():
        if fut.cancelled():
            return
        try:
            result = fn(*args)
        except Exception as e:
            if not fut.cancelled():
                fut.set_exception(e)
        else:
            if not fut.cancelled():
                fut.set_result(result)

    loop.call_soon(_invoke)
    return await fut


class WisprDragonClient:
    """Main client application."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        inject: bool = True,
        mode: Optional[str] = None,
        no_tray: bool = False,
    ):
        """Initialize client.

        Args:
            config_path: Path to client config JSON
            inject: When True, type received transcripts into the focused
                Windows app; when False, only print them.
            mode: Optional override for the hotkey mode ("ptt" or "toggle").
                If None, the value from config (default "ptt") is used.
            no_tray: When True, don't build the system tray icon.
        """
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._default_path = config_path is None  # legacy fallback applies
        self.config = self._load_config()
        self.audio_capture = None
        self.ws_client = None
        self.audio_queue = None
        self._running = False
        self.inject_enabled = inject
        # Injection method from config: "paste" (clipboard + Ctrl+V, default,
        # robust against keystroke-mangling hooks) or "sendinput" (per-char).
        # paste_settle_ms: delay before the previous clipboard is restored —
        # scheduled on the event loop, so a paste never stalls audio capture.
        self.injector = WindowsTextInjector(
            method=self.config.get("inject_method", "paste"),
            paste_settle_ms=self.config.get("paste_settle_ms"),
            scheduler=self._call_later,
        )
        self._mode_override = mode
        self.no_tray = no_tray
        self.hotkey: Optional[Hotkey] = None
        # Why the hotkey listener couldn't start (shown in the tray), or None.
        self.hotkey_error: Optional[str] = None
        self.tray = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # True while the client can't connect until the user enters settings:
        # first-run setup was cancelled, or the server rejected the API key.
        # The client idles in the tray instead of connecting or exiting.
        self.unconfigured = False
        self._setup_dialog = None  # held during exec() to dodge the GC lesson
        # Correction ("correct that"): remember the last text we injected (and
        # the exact length typed, incl. trailing space) so we can backspace over
        # it and retype. None when there's nothing correctable.
        self._last_injection_text: Optional[str] = None
        self._last_injection_len = 0
        # The open (non-modal) correction dialog, or None. While it is open,
        # transcripts drive the dialog instead of being typed.
        self._correction_dialog = None
        # Correlates utterance_start/end with the transcript the server returns.
        self._utterance_id: Optional[str] = None
        # Server refused us with "already connected" (close 4000) since the
        # last `ready`; notified once per episode.
        self._server_busy = False
        # Hotkey pressed while not connected: notified once per outage, and
        # the reconnect backoff is cut short at most every few seconds.
        self._offline_notified = False
        self._last_retry_kick = float("-inf")
        # Auto-closes an idle correction dialog (see _open_correction).
        self._correction_timer = None
        # Process exit code for main() (non-zero: e.g. --no-tray auth failure).
        self.exit_code = 0

    # --- config -----------------------------------------------------------

    def _load_config(self) -> dict:
        """Load client configuration.

        Returns:
            Configuration dictionary
        """
        path = self.config_path
        if not path.exists() and self._default_path:
            legacy = legacy_config_path()
            if legacy is not None and legacy.exists():
                # Pre-XDG clients wrote the Windows path on every OS. Read it
                # once; the next save lands at the native location.
                logger.info("Reading legacy config %s (will save to %s)", legacy, path)
                path = legacy
        if path.exists():
            try:
                # utf-8-sig: Notepad and PowerShell's Out-File write a BOM,
                # which plain json.load rejects.
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError(f"expected a JSON object, got {type(data).__name__}")
                return data
            except Exception as e:
                logger.error("Failed to load config %s: %s", path, e)
                self._backup_bad_config(path)

        return dict(_DEFAULT_CONFIG)

    def _backup_bad_config(self, path: Path) -> None:
        """Copy an unreadable config aside before anything can overwrite it.

        Falling back to defaults means the next save (first-run setup, a mode
        toggle) replaces the file — losing a hand-edited config to one typo.
        """
        bad = path.with_name(path.name + ".bad")
        try:
            shutil.copy2(path, bad)
            logger.error("Unreadable config backed up to %s; using defaults", bad)
        except OSError as e:
            logger.error("Could not back up unreadable config: %s", e)

    def _save_config(self) -> None:
        """Save client configuration atomically (temp file + os.replace).

        A crash or full disk mid-write can no longer leave a truncated
        config.json (which would hold the API key) behind.
        """
        path = self.config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        logger.info("Config saved to %s", path)

    def _try_save_config(self) -> bool:
        """_save_config that reports failure instead of raising."""
        try:
            self._save_config()
            return True
        except Exception as e:
            logger.error("Could not save config %s: %s", self.config_path, e)
            self._notify("Could not save settings", f"{self.config_path}: {e}")
            return False

    # --- lifecycle --------------------------------------------------------

    async def run(self) -> None:
        """Run the client (async main loop)."""
        self._running = True
        self._loop = asyncio.get_running_loop()

        if self.inject_enabled and not self.injector.available:
            logger.warning(
                "Text injection requested but unavailable on this platform — "
                "transcripts will only be printed"
            )
        logger.info(
            "Text injection: %s (method=%s)",
            "on" if (self.inject_enabled and self.injector.available) else "off",
            self.injector.method,
        )

        # First-run setup: if the client has no usable config, prompt for the
        # server URL + key before connecting. GUI-only — the --no-tray path is
        # handled in main() and never reaches here unconfigured. The modal runs
        # outside this Task (see call_outside_task).
        if needs_setup(self.config) and not self.no_tray:
            if await call_outside_task(self._prompt_setup):
                self._try_save_config()
            else:
                # Cancelled: idle in the tray, unconfigured. Build the tray so
                # the user can open Settings later, but don't connect.
                self.unconfigured = True
                logger.info("Setup cancelled — idling in tray (unconfigured)")

        self.audio_queue = asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
        self.audio_capture = WindowsAudioCapture(
            sample_rate=self.config.get("sample_rate", 16000),
            device=self.config.get("device"),
            gate=self._link_up,
        )
        # Start with the mic gated off — the hotkey opens it.
        self.audio_capture.set_paused(True)

        if not self.unconfigured:
            self._build_ws_client()

        self._start_hotkey()
        if not self.no_tray:
            self._start_tray()
            if self.tray is None and self.hotkey is None:
                # No tray and no hotkey: an invisible process holding the
                # instance lock with no way to dictate or quit. Exit instead.
                logger.error("Neither the tray nor the hotkey could start — exiting")
                await self.shutdown()
                return
        if self.hotkey_error:
            # Deferred: a balloon requested in the same tick the tray icon is
            # created can be dropped before the icon is registered.
            self._loop.call_later(1.0, self._notify, "Hotkey unavailable", self.hotkey_error)

        try:
            if self.tray is not None:
                self.tray.update_recording_state(False)
            # Idle in the tray while unconfigured (first-run setup cancelled),
            # until the user enters settings via the tray or quits. open_settings()
            # clears self.unconfigured, so the code below then falls through into
            # the normal connect path — no restart.
            await self._idle_until_configured()

            if self._running and not self.unconfigured and self.ws_client is None:
                self._build_ws_client()

            if self._running and self.ws_client is not None:
                await self._run_session()

        except KeyboardInterrupt:
            logger.info("Client stopped by user")
        except Exception:
            logger.exception("Client error")
        finally:
            await self.shutdown()

    def _start_hotkey(self) -> None:
        """Start the global hotkey; on failure record why (tray shows it)."""
        mode = self._resolve_mode()
        key_name = self.config.get("hotkey", "ctrl_r")
        self.hotkey = Hotkey(
            key_name=key_name,
            mode=mode,
            on_active_changed=self._on_hotkey_changed,
            # Opt-in for software triggers (VoiceAttack, AutoHotkey, Stream
            # Deck, pedals); off so our own paste chord can't drive the hotkey.
            allow_injected=bool(self.config.get("allow_injected_hotkey", False)),
        )
        try:
            self.hotkey.start()
        except Exception as e:
            logger.error("Could not start hotkey listener (hotkey=%r): %s", key_name, e)
            self.hotkey = None
            self.hotkey_error = (
                f"Could not register the dictation hotkey {key_name!r} ({e}). "
                f"Fix \"hotkey\" in {self.config_path} and restart the client."
            )
            return
        logger.info("Hotkey mode: %s (key=%s)", mode.value, key_name)

    def _start_tray(self) -> None:
        try:
            from wispr_dragon.client.tray import TrayApp
            self.tray = TrayApp(self)
            self.tray.start()
        except Exception:
            logger.exception("Tray init failed, continuing without it")
            self.tray = None

    async def _idle_until_configured(self) -> None:
        while self._running and self.unconfigured:
            await asyncio.sleep(0.25)

    async def _run_session(self) -> None:
        """Run audio capture + the server connection until the client stops.

        Neither a lost server, a rejected API key, nor a microphone error ends
        the process any more — each used to make the tray silently vanish. The
        websocket client retries forever with backoff; on an auth rejection we
        idle until the user enters new settings; the mic stream is reopened
        with backoff (_run_audio).
        """
        audio_task = asyncio.create_task(self._run_audio())
        client_task = None
        try:
            while self._running:
                client_task = asyncio.create_task(self.ws_client.run(self.audio_queue))
                done, _ = await asyncio.wait(
                    {audio_task, client_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if audio_task in done:
                    # _run_audio only returns when the client is stopping.
                    if not audio_task.cancelled() and audio_task.exception() is not None:
                        logger.error("Audio loop failed: %r", audio_task.exception())
                    break
                if not self._running:
                    break

                # The websocket client ended on its own.
                exc = None if client_task.cancelled() else client_task.exception()
                if exc is not None:
                    logger.error("Server connection task failed: %r — restarting", exc)
                    await self._sleep_unless_stopped(_AUDIO_RETRY_MIN_S)
                    continue
                if self.ws_client.auth_failed:
                    self._on_auth_failed()
                    await self._idle_until_configured()
                    if not self._running:
                        break
                    self._build_ws_client()
                    if self.tray is not None:
                        self.tray.set_status("")
                    continue
                logger.warning("Server connection ended unexpectedly — restarting")
                await self._sleep_unless_stopped(_AUDIO_RETRY_MIN_S)
        finally:
            self._running = False
            self.audio_capture.stop()
            if self.ws_client is not None:
                self.ws_client.stop()
            tasks = [t for t in (audio_task, client_task) if t is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _on_auth_failed(self) -> None:
        """Server rejected the API key: idle (no reconnects) until Settings.

        Without a tray there is no Settings to wait for — idling would just
        hold the instance lock, mic and hotkey forever — so exit instead.
        """
        self.unconfigured = True
        self.ws_client = None
        if self.tray is None:
            logger.error(
                "The server rejected the API key. Fix \"api_key\" in %s (run the "
                "server with --print-key to see it) and start the client again.",
                self.config_path,
            )
            self.exit_code = EXIT_AUTH_FAILED
            self.stop()
            return
        logger.error("Authentication failed — waiting for new settings (tray > Settings)")
        if self.tray is not None:
            self.tray.set_status("authentication failed")
        self._notify(
            "Authentication failed",
            "The server rejected the API key. Open Settings from the tray menu "
            "to enter the correct key.",
        )

    async def _run_audio(self) -> None:
        """Keep the microphone stream open, reopening it if it fails."""
        loop = asyncio.get_running_loop()
        delay = _AUDIO_RETRY_MIN_S
        notified = False
        while self._running:
            started = loop.time()
            await self.audio_capture.start(self.audio_queue)
            if not self._running:
                return
            if loop.time() - started >= _AUDIO_HEALTHY_S:
                delay, notified = _AUDIO_RETRY_MIN_S, False
            error = self.audio_capture.error or "the audio stream stopped unexpectedly"
            logger.error("Microphone unavailable (%s) — retrying in %d s", error, delay)
            if not notified:
                notified = True
                self._notify(
                    "Microphone unavailable",
                    f"{error}\nCheck the input device; retrying automatically.",
                )
            await self._sleep_unless_stopped(delay)
            delay = min(delay * 2, _AUDIO_RETRY_MAX_S)

    async def _sleep_unless_stopped(self, seconds: float) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while self._running:
            remaining = end - loop.time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.25, remaining))

    async def shutdown(self) -> None:
        """Shutdown the client."""
        self._running = False
        if self.hotkey:
            self.hotkey.stop()
        if self.audio_capture:
            self.audio_capture.stop()
        # Hand the user's clipboard back now rather than on a timer that may
        # never fire once the loop stops.
        flush = getattr(self.injector, "flush_restore", None)
        if flush is not None:
            with contextlib.suppress(Exception):
                flush()
        if self._correction_dialog is not None:
            with contextlib.suppress(Exception):
                self._correction_dialog.reject()
            self._correction_dialog = None
        if self.tray:
            self.tray.stop()
        if self.ws_client:
            try:
                await asyncio.wait_for(
                    self.ws_client.disconnect(), timeout=_SHUTDOWN_DISCONNECT_S
                )
            except Exception as e:
                logger.warning("Server disconnect did not finish cleanly: %s", e)
        logger.info("Client shut down")

    def stop(self) -> None:
        """Synchronously request shutdown — safe to call from the tray menu.

        Sets the running flags on the audio + ws subtasks so run() unwinds and
        its finally block runs the real async cleanup.
        """
        self._running = False
        if self.audio_capture:
            self.audio_capture.stop()
        if self.ws_client:
            self.ws_client.stop()

    def _notify(self, title: str, message: str) -> None:
        """Surface a problem in the tray (the only UI of the windowed build)."""
        if self.tray is not None:
            self.tray.notify(title, message)

    def _call_later(self, delay: float, callback: Callable[[], None]):
        """Injector scheduler: run ``callback`` on the event loop after
        ``delay`` s. Returns a cancellable handle, or None (no running loop
        yet), in which case the injector falls back to restoring inline."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return None
        return loop.call_later(delay, callback)

    # --- setup / settings -------------------------------------------------

    def _build_ws_client(self) -> None:
        """(Re)create the WebSocket client from current config."""
        self.ws_client = WebSocketClient(
            server_url=self.config.get("server_url", "ws://localhost:8765"),
            api_key=self.config.get("api_key", ""),
            on_transcript=self._on_transcript,
            on_error=self._on_error,
            on_status=self._on_status,
        )

    def _prompt_setup(self) -> bool:
        """Show the modal setup dialog. Returns True if saved, False if cancelled.

        Blocks in QDialog.exec(): call it from a Qt slot or via
        call_outside_task(), never directly inside an asyncio Task.

        Requires a QApplication (tray path). Returns False if Qt is unavailable
        so callers fall back to the unconfigured/idle behaviour.
        """
        if self._setup_dialog is not None:
            # Already open (e.g. Settings clicked twice) — just surface it.
            with contextlib.suppress(Exception):
                self._setup_dialog.raise_()
                self._setup_dialog.activateWindow()
            return False
        try:
            from PyQt6.QtWidgets import QApplication
            from wispr_dragon.client.setup_dialog import SetupDialog
        except ImportError as e:
            logger.warning("Setup dialog unavailable (%s)", e)
            return False
        if QApplication.instance() is None:
            return False
        # Hold a reference for the dialog's lifetime (the QAction GC lesson).
        self._setup_dialog = SetupDialog(self.config)
        try:
            accepted = bool(self._setup_dialog.exec())
            if accepted:
                result = self._setup_dialog.result_config()
                if result:
                    self.config = result
                    return True
            return False
        finally:
            self._setup_dialog = None

    def open_settings(self) -> None:
        """Open the setup dialog at runtime (from the tray) and apply changes.

        On a server URL / key change, reconnect promptly with the new values.
        If the client was idling unconfigured (setup cancelled, or the server
        rejected the key), this transitions it into the connect path.
        """
        old = (self.config.get("server_url"), self.config.get("api_key"))
        if not self._prompt_setup():
            return
        self._try_save_config()
        new = (self.config.get("server_url"), self.config.get("api_key"))

        if self.unconfigured:
            # run()'s idle loop will pick this up and build the ws_client.
            self.unconfigured = False
            logger.info("Settings entered — connecting")
            return
        if new != old and self.ws_client is not None:
            logger.info("Server settings changed — reconnecting")
            self.ws_client.server_url = self.config.get("server_url", "ws://localhost:8765")
            self.ws_client.api_key = self.config.get("api_key", "")
            self.ws_client.reconnect_now()
            # Drop the current socket; run()'s loop re-establishes it.
            if self._loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self.ws_client._close_socket(), self._loop
                )

    # --- hotkey integration ----------------------------------------------

    def _resolve_mode(self) -> HotkeyMode:
        raw = self._mode_override or self.config.get("mode", "ptt")
        try:
            return HotkeyMode(raw)
        except ValueError:
            logger.warning("Unknown mode %r, defaulting to PTT", raw)
            return HotkeyMode.PTT

    def set_mode(self, mode: HotkeyMode) -> None:
        """Switch hotkey mode (called from the tray) and persist to config."""
        if self.hotkey is not None:
            self.hotkey.set_mode(mode)
        self.config["mode"] = mode.value
        try:
            self._save_config()
        except Exception as e:
            logger.warning("Could not persist mode change: %s", e)

    def _on_hotkey_changed(self, active: bool) -> None:
        """Hotkey callback — runs on pynput's listener thread."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._apply_active, active)

    def _utterance_framing(self) -> bool:
        """True when the server can transcribe a whole hotkey-delimited utterance."""
        return self.ws_client is not None and self.ws_client.supports("utterance")

    def _link_up(self) -> bool:
        """True while connected to the server. Audio and control frames are
        only queued then: anything queued during an outage would be stale (and
        unbounded) by the time the link returns."""
        return self.ws_client is not None and self.ws_client.is_connected

    def _enqueue_control(self, message: dict) -> None:
        """Queue a control frame behind any pending audio (order matters).

        Control frames must not be lost to a full queue (a dropped
        utterance_end leaves the server buffering until its valve fires). Audio
        capture leaves CONTROL_HEADROOM slots free for them; if the queue is
        full anyway, the oldest *audio* frame is evicted — never another
        control frame, which would break utterance framing.
        """
        queue = self.audio_queue
        if queue is None or not self._link_up():
            logger.debug("Not connected — control frame %s not sent", message.get("type"))
            return
        try:
            queue.put_nowait(message)
            return
        except asyncio.QueueFull:
            pass
        items = []
        while True:
            try:
                items.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        victim = next((i for i, it in enumerate(items) if not isinstance(it, dict)), None)
        if victim is not None:
            del items[victim]
        for it in items:
            queue.put_nowait(it)
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.error("Queue full of control frames — dropped %s", message.get("type"))

    def _apply_active(self, active: bool) -> None:
        """Mic gate change — runs on the asyncio event loop thread.

        The hotkey is the utterance boundary. Against a server that understands
        utterance framing we say so explicitly, and the whole utterance is
        transcribed in one pass. Against an older server we fall back to the
        silence-flush hack, which nudges its VAD into closing the last segment.
        """
        if self.audio_capture is None:
            return
        if active:
            if self._utterance_framing():
                self._utterance_id = uuid.uuid4().hex
                self._enqueue_control({"type": "utterance_start", "id": self._utterance_id})
            self.audio_capture.set_paused(False)
            if not self._link_up():
                self._on_record_while_offline()
            logger.info("Recording ON - speak now")
        else:
            self.audio_capture.set_paused(True)
            if self._utterance_framing():
                self._enqueue_control({"type": "utterance_end", "id": self._utterance_id})
                self._utterance_id = None
            elif self._link_up() and self.audio_queue is not None:
                # Legacy server: inject a tail of silence so its VAD flushes the
                # last segment instead of leaving it buffered (audio, so it
                # respects the control-frame headroom too).
                limit = max(1, self.audio_queue.maxsize - CONTROL_HEADROOM)
                for _ in range(_FLUSH_FRAMES):
                    if self.audio_queue.maxsize and self.audio_queue.qsize() >= limit:
                        break
                    self.audio_queue.put_nowait(_SILENCE_FRAME)
            logger.info("Recording OFF")
        if self.tray is not None:
            self.tray.update_recording_state(active)

    def _on_record_while_offline(self) -> None:
        """The hotkey went hot with no server link: this speech goes nowhere.

        Say so (once per outage — the tray icon alone turns red as usual) and
        cut the reconnect backoff short, rate-limited.
        """
        logger.warning("Recording ON, but not connected to the server")
        now = _monotonic()
        if self.ws_client is not None and now - self._last_retry_kick >= _RETRY_KICK_MIN_S:
            self._last_retry_kick = now
            self.ws_client.retry_now()
        if self._offline_notified:
            return
        self._offline_notified = True
        if self.ws_client is None:
            message = ("Wispr Dragon isn't set up to reach a server. Open Settings "
                       "from the tray menu.")
        else:
            message = ("Not connected to the Wispr Dragon server, so this dictation "
                       "can't be transcribed. Reconnecting now…")
        self._notify("Not connected", message)

    # --- transcripts + correction ----------------------------------------

    def _on_transcript(self, text: str) -> None:
        """Handle received transcription.

        Args:
            text: Transcribed text from server
        """
        if self.inject_enabled and self.injector.available:
            # Dictated text is private: it goes into the focused app, and to
            # the log only at DEBUG — never to stdout.
            logger.debug("Transcript: %s", text)
        else:
            # --no-inject (or no injection on this platform): printing is
            # the only output, by contract.
            _echo_transcript(text)

        # While the correction window is open, speech drives it ("choose 2",
        # "cancel", or a freehand correction) instead of being typed into the
        # focused field — which may well be the correction window itself.
        if self._correction_dialog is not None:
            self._route_to_correction(text)
            return

        # "correct that" — open the correction window on the last utterance
        # instead of injecting the command itself. Scheduled as a plain loop
        # callback: this runs inside the websocket listen() Task, and Qt UI
        # work must never block or nest an event loop inside a Task.
        if is_correct_trigger(text):
            if self._loop is not None:
                self._loop.call_soon(self._open_correction)
            else:
                self._open_correction()
            return

        if self.inject_enabled:
            clean = sanitize_text(text)
            if not clean:
                return
            # Trailing space so consecutive phrases don't run together — but
            # not after a dictated newline/tab (it would start the next line
            # with a stray space).
            payload = clean if clean[-1].isspace() else clean + " "
            if self.injector.inject(payload):
                self._last_injection_text = clean
                self._last_injection_len = len(payload)

    def _route_to_correction(self, text: str) -> None:
        dlg = self._correction_dialog
        self._touch_correction()
        if is_correct_trigger(text):
            return  # already open
        selection = parse_selection(text)
        if selection is None:
            dlg.correction_input.setText(sanitize_text(text).strip())
        elif selection["action"] == "cancel":
            dlg.reject()
        elif selection["action"] == "choose":
            if dlg.select_index(selection["index"]):
                dlg.apply_now()

    def _open_correction(self) -> None:
        """Show the correction dialog for the last injected utterance.

        Non-blocking: ``open()`` + the ``finished`` signal, never ``exec()``.
        """
        if self._correction_dialog is not None:
            with contextlib.suppress(Exception):
                self._correction_dialog.raise_()
                self._correction_dialog.activateWindow()
            return
        if self._last_injection_text is None:
            logger.info("Nothing to correct yet")
            return
        if not self.injector.available:
            logger.warning("Correction needs text injection (Windows only) — skipped")
            return
        try:
            from PyQt6.QtWidgets import QApplication
            from wispr_dragon.client.correction_dialog import CorrectionDialog
        except ImportError as e:
            logger.warning("Correction dialog unavailable (%s)", e)
            return
        if QApplication.instance() is None:
            return

        from PyQt6.QtCore import QTimer

        original = self._last_injection_text
        dlg = CorrectionDialog(original, dictionary=None)
        self._correction_dialog = dlg  # also keeps it alive (GC lesson)
        dlg.finished.connect(
            lambda code, d=dlg, o=original: self._on_correction_finished(d, o, code)
        )
        # While the dialog is open it captures all dictation, so it must not
        # linger forgotten (e.g. hidden behind the app by Windows' foreground
        # lock): close it after a stretch with no speech or edits.
        timer = QTimer(dlg)
        timer.setSingleShot(True)
        timer.setInterval(_CORRECTION_IDLE_TIMEOUT_MS)
        timer.timeout.connect(dlg.reject)
        self._correction_timer = timer
        dlg.correction_input.textEdited.connect(self._touch_correction)
        dlg.list_widget.currentRowChanged.connect(self._touch_correction)
        dlg.always_apply.toggled.connect(self._touch_correction)
        dlg.open()
        with contextlib.suppress(Exception):
            dlg.raise_()
            dlg.activateWindow()
        timer.start()
        self._notify(
            "Correction window open",
            "Say \"choose N\" to pick an alternative, dictate the fix, or say "
            "\"cancel\" to close. Dictation goes to this window until it closes.",
        )

    def _touch_correction(self, *_args) -> None:
        """Restart the correction dialog's idle timeout."""
        if self._correction_timer is not None:
            with contextlib.suppress(RuntimeError):  # C++ timer already gone
                self._correction_timer.start()

    def _on_correction_finished(self, dlg, original: str, code: int) -> None:
        if self._correction_dialog is dlg:
            self._correction_dialog = None
            self._correction_timer = None
        result = dlg.result_correction() if code else None
        dlg.deleteLater()
        if not result:
            return

        corrected, always = result
        if corrected == original:
            return
        # Replace the injected text in the focused field: backspace the old
        # (incl. trailing space) and retype the correction + space.
        replacement = corrected if corrected[-1:].isspace() else corrected + " "
        if self.injector.replace_last(self._last_injection_len, replacement):
            self._last_injection_text = corrected
            self._last_injection_len = len(replacement)
            logger.info("Correction applied")
            logger.debug("Corrected %r -> %r", original, corrected)
            self._learn_correction(original.strip(), corrected.strip(), always)

    def _learn_correction(self, wrong: str, correct: str, always: bool) -> None:
        """Send the learned correction to the server to persist + auto-apply."""
        if self.ws_client is None or self._loop is None:
            return
        msg = {"type": "learn_correction", "wrong": wrong, "correct": correct, "always": always}
        try:
            asyncio.run_coroutine_threadsafe(self.ws_client.send_json(msg), self._loop)
        except Exception as e:
            logger.warning("Could not send learned correction: %s", e)

    def _on_error(self, error: str) -> None:
        """Handle error from server.

        Args:
            error: Error message
        """
        # WebSocketClient already logged it at the right level; don't repeat.
        logger.debug("Error: %s", error)

    def _on_status(self, status: str) -> None:
        """Handle connection status change.

        Args:
            status: New status (connected, ready, busy, unauthorized,
                connect_failed, disconnected, reconnecting (n))
        """
        logger.info("Status: %s", status)
        if status == "ready":
            self._server_busy = False
            self._offline_notified = False
        elif status in ("connect_failed", "unauthorized"):
            # A different problem now; "server busy" no longer describes it.
            self._server_busy = False
        elif status == "busy" and not self._server_busy:
            self._server_busy = True
            self._notify(
                "Server busy",
                "Another client is connected to the Wispr Dragon server. "
                "Retrying automatically; quit the other client to connect.",
            )
        if self.tray is None:
            return
        if status in ("connected", "ready"):
            self.tray.set_status("")
        elif status == "unauthorized":
            self.tray.set_status("authentication failed")
        elif self._server_busy:
            self.tray.set_status("server busy - another client is connected")
        elif status.startswith("reconnecting") or status in ("disconnected", "connect_failed"):
            self.tray.set_status("not connected - retrying")


def _echo_transcript(text: str) -> None:
    """Print a transcript to stdout (terminal runs). Never raises: the windowed
    build has no stdout, and a cp1252 console can't encode every character —
    either used to throw inside the websocket listener and drop the link."""
    if sys.stdout is None:
        return
    try:
        print(f"[TRANSCRIPT] {text}", flush=True)
    except Exception:
        with contextlib.suppress(Exception):
            print("[TRANSCRIPT] " + text.encode("ascii", "replace").decode("ascii"), flush=True)


def configure_logging(
    log_dir: Optional[Path] = None, level: int = logging.INFO, to_file: bool = True
) -> Optional[Path]:
    """Log to stderr (when there is one) and, with ``to_file``, to client.log.

    The windowed (console=False) build has ``sys.stderr is None``, so without
    the file every log line — "already running", auth failures, crashes — was
    simply dropped. Returns the log file path, or None if there is none.
    """
    root = logging.getLogger()
    root.setLevel(level)
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"
        ))
        root.addHandler(stream)
    if not to_file:
        return None
    handler = add_file_logging(log_dir)
    return Path(handler.baseFilename) if handler is not None else None


def add_file_logging(log_dir: Optional[Path] = None) -> Optional[logging.Handler]:
    """Attach the rotating client.log handler (utf-8, 1 MB x 3) to the root logger."""
    log_dir = log_dir or default_config_dir()
    log_path = log_dir / LOG_FILENAME
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True
        )
    except OSError as e:
        logger.warning("File logging unavailable (%s): %s", log_path, e)
        return None
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logging.getLogger().addHandler(handler)
    return handler


def _remove_handler(handler: Optional[logging.Handler]) -> None:
    if handler is not None:
        logging.getLogger().removeHandler(handler)
        handler.close()


def install_excepthooks() -> None:
    """Log uncaught exceptions instead of losing them (or aborting).

    PyQt6 calls ``qFatal`` — killing the process — when a slot raises and
    ``sys.excepthook`` is the default; with a custom hook it just reports. A
    Settings save hitting a PermissionError must not take the client down.
    """
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread is not None else "?"
        logger.critical(
            "Unhandled exception in thread %s", name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def _show_error_box(title: str, text: str) -> None:
    """Best-effort message box for a console-less process; logs if Qt is missing."""
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        return
    try:
        _app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
        QMessageBox.warning(None, title, text)
    except Exception as e:
        logger.warning("Could not show message box: %s", e)


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Wispr Dragon Client")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices")
    parser.add_argument(
        "--no-inject", action="store_true",
        help="Don't type transcripts into the focused window — just print them",
    )
    parser.add_argument(
        "--mode", choices=["ptt", "toggle"],
        help="Hotkey mode override (default: value from config, falling back to ptt)",
    )
    parser.add_argument(
        "--no-tray", action="store_true",
        help="Run without the system tray icon (headless)",
    )
    args = parser.parse_args()

    if args.list_devices:
        WindowsAudioCapture.list_devices()
        return 0

    configure_logging(to_file=False)  # client.log is added once we own the lock
    install_excepthooks()

    # Refuse to start a second client. Two instances fight over the single
    # server connection, the global hotkey, and the microphone. Held for the
    # process lifetime (released by the OS on exit).
    instance_lock = acquire_single_instance()
    if instance_lock is None:
        # Record the refusal in client.log, then let go of the file at once:
        # the running instance owns it (on Windows its rotation fails while
        # another process holds the file), and the box below may stay up.
        refusal_log = add_file_logging()
        logger.error(
            "Another Wispr Dragon client is already running. The server accepts "
            "only one connection, and a second client would also grab the hotkey "
            "and microphone. Quit the other instance first."
        )
        _remove_handler(refusal_log)
        if not args.no_tray and sys.stderr is None:
            # Windowed build: nobody sees the log line above.
            _show_error_box(
                "Wispr Dragon",
                "Wispr Dragon is already running - look for its icon in the "
                "system tray. Quit that instance before starting another.",
            )
        return 3

    file_log = add_file_logging()
    if file_log is not None:
        logger.info("Logging to %s", file_log.baseFilename)

    client = WisprDragonClient(
        config_path=(Path(args.config) if args.config else None),
        inject=not args.no_inject,
        mode=args.mode,
        no_tray=args.no_tray,
    )

    if args.no_tray:
        # Headless has no GUI to enter setup — fail fast with an actionable hint
        # rather than blocking or reconnect-storming a server with an empty key.
        if needs_setup(client.config):
            logger.error(
                "Client is not configured (missing server_url or api_key) and "
                "--no-tray has no setup UI. Run the server with --print-key, then "
                "set both fields in %s (or launch without --no-tray to use the "
                "setup dialog).",
                client.config_path,
            )
            return 2
        try:
            asyncio.run(client.run())
        except KeyboardInterrupt:
            pass
        return client.exit_code

    return _run_with_tray(client)


def _run_with_tray(client) -> int:
    """Run the client with a Qt system-tray UI alongside asyncio (qasync)."""
    try:
        from PyQt6.QtWidgets import QApplication
        import qasync
    except ImportError as e:
        logger.error(
            "Tray UI dependencies missing (%s). "
            "Run with --no-tray, or `pip install PyQt6 qasync pynput` in this env.",
            e,
        )
        return 1

    qt_app = QApplication.instance() or QApplication(sys.argv)
    # Closing the (invisible) tray "window" should not exit the program.
    qt_app.setQuitOnLastWindowClosed(False)
    # If Qt quits by any route (tray Quit, session logout, window close), ask the
    # client to wind down so run() can finish rather than being torn out from
    # under qasync.
    qt_app.aboutToQuit.connect(client.stop)
    loop = qasync.QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    with loop:
        try:
            loop.run_until_complete(client.run())
        except KeyboardInterrupt:
            pass
        except RuntimeError as e:
            # qasync raises "Event loop stopped before Future completed" when the
            # Qt loop stops while run() is still unwinding. Shutdown has already
            # happened at that point, so this is noise, not a failure — surfacing
            # it as an unhandled exception showed users a crash dialog on Quit.
            if "Event loop stopped before Future completed" not in str(e):
                raise
            logger.debug("Qt loop stopped during shutdown: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
