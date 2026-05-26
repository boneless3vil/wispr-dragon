"""Main client application for Wispr Dragon."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from wispr_dragon.client.audio_capture import WindowsAudioCapture
from wispr_dragon.client.hotkey import Hotkey, HotkeyMode
from wispr_dragon.client.websocket_client import WebSocketClient
from wispr_dragon.client.windows_injector import WindowsTextInjector

# 30 ms of int16 mono silence at 16 kHz, used to flush the server's VAD when
# the hotkey releases so the last word of a phrase doesn't get buffered.
_SILENCE_FRAME = b"\x00\x00" * 480
_FLUSH_FRAMES = 33  # ~1 second — well past the VAD's silence threshold

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / "AppData" / "Local" / "WisprDragon" / "config.json"


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

        self.audio_queue = asyncio.Queue()
        self.audio_capture = WindowsAudioCapture(
            sample_rate=self.config.get("sample_rate", 16000),
            device=self.config.get("device"),
        )
        # Start with the mic gated off — the hotkey opens it.
        self.audio_capture.set_paused(True)

        self.ws_client = WebSocketClient(
            server_url=self.config.get("server_url", "ws://localhost:8765"),
            api_key=self.config.get("api_key", ""),
            on_transcript=self._on_transcript,
            on_error=self._on_error,
            on_status=self._on_status,
        )

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
            audio_task = asyncio.create_task(self.audio_capture.start(self.audio_queue))
            client_task = asyncio.create_task(self.ws_client.run(self.audio_queue))

            await asyncio.gather(audio_task, client_task)

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
            logger.debug("Mic ON")
        else:
            # Inject a brief tail of silence so the server's VAD flushes the
            # last segment instead of leaving it buffered.
            for _ in range(_FLUSH_FRAMES):
                try:
                    self.audio_queue.put_nowait(_SILENCE_FRAME)
                except asyncio.QueueFull:
                    break
            self.audio_capture.set_paused(True)
            logger.debug("Mic OFF (flushed VAD)")
        if self.tray is not None:
            self.tray.update_recording_state(active)

    def _on_transcript(self, text: str) -> None:
        """Handle received transcription.

        Args:
            text: Transcribed text from server
        """
        print(f"[TRANSCRIPT] {text}")
        if self.inject_enabled:
            # Trailing space so consecutive phrases don't run together.
            self.injector.inject(text + " ")

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
