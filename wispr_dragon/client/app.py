"""Main client application for Wispr Dragon."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from wispr_dragon.client.audio_capture import WindowsAudioCapture
from wispr_dragon.client.correction_commands import is_correct_trigger
from wispr_dragon.client.hotkey import Hotkey, HotkeyMode
from wispr_dragon.client.websocket_client import WebSocketClient
from wispr_dragon.client.windows_injector import WindowsTextInjector

# 30 ms of int16 mono silence at 16 kHz, used to flush the server's VAD when
# the hotkey releases so the last word of a phrase doesn't get buffered.
_SILENCE_FRAME = b"\x00\x00" * 480
_FLUSH_FRAMES = 33  # ~1 second — well past the VAD's silence threshold

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / "AppData" / "Local" / "WisprDragon" / "config.json"


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
        self.config = self._load_config()
        self.audio_capture = None
        self.ws_client = None
        self.audio_queue = None
        self._running = False
        self.inject_enabled = inject
        self.injector = WindowsTextInjector()
        self._mode_override = mode
        self.no_tray = no_tray
        self.hotkey: Optional[Hotkey] = None
        self.tray = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Set True when first-run setup was cancelled — the client idles in the
        # tray (unconfigured) instead of connecting or exiting.
        self.unconfigured = False
        self._setup_dialog = None  # held during exec() to dodge the GC lesson
        # Correction ("correct that"): remember the last text we injected (and
        # the exact length typed, incl. trailing space) so we can backspace over
        # it and retype. None when there's nothing correctable.
        self._last_injection_text: Optional[str] = None
        self._last_injection_len = 0
        self._correction_dialog = None  # held during exec()

    def _load_config(self) -> dict:
        """Load client configuration.

        Returns:
            Configuration dictionary
        """
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load config: %s", e)

        return {
            "server_url": "ws://localhost:8765",
            "api_key": "",
            "sample_rate": 16000,
            "device": None,
            "mode": "ptt",
            "hotkey": "ctrl_r",
        }

    def _save_config(self) -> None:
        """Save client configuration."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=2)
        logger.info("Config saved to %s", self.config_path)

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
            "Text injection: %s",
            "on" if (self.inject_enabled and self.injector.available) else "off",
        )

        # First-run setup: if the client has no usable config, prompt for the
        # server URL + key before connecting. GUI-only — the --no-tray path is
        # handled in main() and never reaches here unconfigured.
        if needs_setup(self.config) and not self.no_tray:
            if self._prompt_setup():
                self._save_config()
            else:
                # Cancelled: idle in the tray, unconfigured. Build the tray so
                # the user can open Settings later, but don't connect.
                self.unconfigured = True
                logger.info("Setup cancelled — idling in tray (unconfigured)")

        self.audio_queue = asyncio.Queue()
        self.audio_capture = WindowsAudioCapture(
            sample_rate=self.config.get("sample_rate", 16000),
            device=self.config.get("device"),
        )
        # Start with the mic gated off — the hotkey opens it.
        self.audio_capture.set_paused(True)

        if not self.unconfigured:
            self._build_ws_client()

        mode = self._resolve_mode()
        self.hotkey = Hotkey(
            key_name=self.config.get("hotkey", "ctrl_r"),
            mode=mode,
            on_active_changed=self._on_hotkey_changed,
        )
        try:
            self.hotkey.start()
        except Exception as e:
            logger.error("Could not start hotkey listener: %s", e)
            self.hotkey = None
        logger.info("Hotkey mode: %s (key=%s)", mode.value, self.config.get("hotkey", "ctrl_r"))

        if not self.no_tray:
            try:
                from wispr_dragon.client.tray import TrayApp
                self.tray = TrayApp(self)
                self.tray.start()
            except Exception as e:
                logger.warning("Tray init failed, continuing without it: %s", e)
                self.tray = None

        try:
            # Idle in the tray while unconfigured (first-run setup cancelled),
            # until the user enters settings via the tray or quits. open_settings()
            # clears self.unconfigured and builds the ws_client, so the loop below
            # then falls through into the normal connect path — no restart.
            if self.tray is not None:
                self.tray.update_recording_state(False)
            while self._running and self.unconfigured:
                await asyncio.sleep(0.25)

            if self._running and not self.unconfigured and self.ws_client is None:
                self._build_ws_client()

            if self._running and self.ws_client is not None:
                audio_task = asyncio.create_task(self.audio_capture.start(self.audio_queue))
                client_task = asyncio.create_task(self.ws_client.run(self.audio_queue))

                # Stop as soon as EITHER task ends — e.g. the WebSocket client
                # giving up after an auth failure. Using gather() here would keep
                # waiting on the (endless) audio task, so the process never shut
                # down and the tray icon lingered. FIRST_COMPLETED + teardown
                # guarantees shutdown.
                done, pending = await asyncio.wait(
                    {audio_task, client_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                self._running = False
                self.audio_capture.stop()
                self.ws_client.stop()
                for task in pending:
                    task.cancel()
                await asyncio.gather(audio_task, client_task, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("Client stopped by user")
        except Exception as e:
            logger.error("Client error: %s", e)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown the client."""
        self._running = False
        if self.hotkey:
            self.hotkey.stop()
        if self.audio_capture:
            self.audio_capture.stop()
        if self.tray:
            self.tray.stop()
        if self.ws_client:
            await self.ws_client.disconnect()
        logger.info("Client shut down")

    def stop(self) -> None:
        """Synchronously request shutdown — safe to call from the tray menu.

        Sets the running flags on the audio + ws subtasks so the gather() in
        run() unblocks and the finally block runs the real async cleanup.
        """
        self._running = False
        if self.audio_capture:
            self.audio_capture.stop()
        if self.ws_client:
            self.ws_client.stop()

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

        Requires a QApplication (tray path). Returns False if Qt is unavailable
        so callers fall back to the unconfigured/idle behaviour.
        """
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

        On a server URL / key change, rebuild the WebSocket client so the run
        loop reconnects with the new values (one reconnect). If the client was
        idling unconfigured, this transitions it into the connect path.
        """
        old = (self.config.get("server_url"), self.config.get("api_key"))
        if not self._prompt_setup():
            return
        self._save_config()
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
            self.ws_client._reconnect_count = 0
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

    def _apply_active(self, active: bool) -> None:
        """Mic gate change — runs on the asyncio event loop thread."""
        if active:
            self.audio_capture.set_paused(False)
            logger.info("🎤 Recording ON — speak now")
        else:
            # Inject a brief tail of silence so the server's VAD flushes the
            # last segment instead of leaving it buffered.
            for _ in range(_FLUSH_FRAMES):
                try:
                    self.audio_queue.put_nowait(_SILENCE_FRAME)
                except asyncio.QueueFull:
                    break
            self.audio_capture.set_paused(True)
            logger.info("Recording OFF")
        if self.tray is not None:
            self.tray.update_recording_state(active)

    def _on_transcript(self, text: str) -> None:
        """Handle received transcription.

        Args:
            text: Transcribed text from server
        """
        print(f"[TRANSCRIPT] {text}")

        # "correct that" — open the correction window on the last utterance
        # instead of injecting the command itself.
        if is_correct_trigger(text):
            self._open_correction()
            return

        if self.inject_enabled:
            # Trailing space so consecutive phrases don't run together.
            payload = text + " "
            if self.injector.inject(payload):
                self._last_injection_text = text
                self._last_injection_len = len(payload)

    def _open_correction(self) -> None:
        """Show the correction dialog for the last injected utterance."""
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

        original = self._last_injection_text
        self._correction_dialog = CorrectionDialog(original, dictionary=None)
        try:
            if not self._correction_dialog.exec():
                return
            result = self._correction_dialog.result_correction()
        finally:
            self._correction_dialog = None
        if not result:
            return

        corrected, always = result
        if corrected == original:
            return
        # Replace the injected text in the focused field: backspace the old
        # (incl. trailing space) and retype the correction + space.
        replacement = corrected + " "
        if self.injector.replace_last(self._last_injection_len, replacement):
            self._last_injection_text = corrected
            self._last_injection_len = len(replacement)
            logger.info("Corrected '%s' -> '%s'", original, corrected)
            self._learn_correction(original, corrected, always)

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
        logger.error("Error: %s", error)

    def _on_status(self, status: str) -> None:
        """Handle connection status change.

        Args:
            status: New status (connected, disconnected, reconnecting, etc.)
        """
        logger.info("Status: %s", status)


def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

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
        return 0

    return _run_with_tray(client)


def _run_with_tray(client) -> int:
    """Run the client with a Qt system-tray UI alongside asyncio (qasync)."""
    try:
        import sys
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
    loop = qasync.QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    with loop:
        try:
            loop.run_until_complete(client.run())
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
