"""Main client application for Wispr Dragon."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from wispr_dragon.client.audio_capture import WindowsAudioCapture
from wispr_dragon.client.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / "AppData" / "Local" / "WisprDragon" / "config.json"


class WisprDragonClient:
    """Main client application."""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize client.

        Args:
            config_path: Path to client config JSON
        """
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config = self._load_config()
        self.audio_capture = None
        self.ws_client = None
        self.audio_queue = None
        self._running = False

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
            "server_url": "ws://192.168.1.x:8765",
            "api_key": "",
            "sample_rate": 16000,
            "device": None,
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

        self.audio_queue = asyncio.Queue()
        self.audio_capture = WindowsAudioCapture(
            sample_rate=self.config.get("sample_rate", 16000),
            device=self.config.get("device"),
        )
        self.ws_client = WebSocketClient(
            server_url=self.config.get("server_url", "ws://localhost:8765"),
            api_key=self.config.get("api_key", ""),
            on_transcript=self._on_transcript,
            on_error=self._on_error,
            on_status=self._on_status,
        )

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
        if self.audio_capture:
            self.audio_capture.stop()
        if self.ws_client:
            await self.ws_client.disconnect()
        logger.info("Client shut down")

    def _on_transcript(self, text: str) -> None:
        """Handle received transcription.

        Args:
            text: Transcribed text from server
        """
        print(f"[TRANSCRIPT] {text}")

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
    args = parser.parse_args()

    if args.list_devices:
        WindowsAudioCapture.list_devices()
        return 0

    client = WisprDragonClient(Path(args.config) if args.config else None)
    asyncio.run(client.run())
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
