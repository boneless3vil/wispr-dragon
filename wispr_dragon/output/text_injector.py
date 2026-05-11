"""Inject transcribed text into the active window."""

import logging
import subprocess
import shutil
from typing import Optional

logger = logging.getLogger(__name__)


class TextInjector:
    """Injects text into the active window using xdotool or clipboard.

    xdotool is the primary method for Linux/WSLg windows.
    Clipboard fallback uses xclip + xdotool key ctrl+v.
    """

    def __init__(self, method: str = "auto"):
        self._method = method
        if method == "auto":
            self._method = self._detect_method()

    def _detect_method(self) -> str:
        if shutil.which("xdotool"):
            return "xdotool"
        if shutil.which("xclip"):
            return "clipboard"
        if shutil.which("wl-copy"):
            return "wl-clipboard"
        logger.warning("No text injection method available")
        return "print"

    def inject(self, text: str) -> None:
        """Inject text into the active window."""
        if self._method == "xdotool":
            self._inject_xdotool(text)
        elif self._method == "clipboard":
            self._inject_clipboard_x11(text)
        elif self._method == "wl-clipboard":
            self._inject_clipboard_wayland(text)
        else:
            print(text, end="", flush=True)

    def _inject_xdotool(self, text: str) -> None:
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "10", text],
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            logger.error("xdotool timed out")
        except FileNotFoundError:
            logger.error("xdotool not found, falling back to print")
            print(text, end="", flush=True)

    def _inject_clipboard_x11(self, text: str) -> None:
        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
            )
            proc.communicate(text.encode())
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                timeout=2,
            )
        except Exception as e:
            logger.error("Clipboard injection failed: %s", e)
            print(text, end="", flush=True)

    def _inject_clipboard_wayland(self, text: str) -> None:
        try:
            proc = subprocess.Popen(
                ["wl-copy"],
                stdin=subprocess.PIPE,
            )
            proc.communicate(text.encode())
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                timeout=2,
            )
        except Exception as e:
            logger.error("Wayland clipboard injection failed: %s", e)
            print(text, end="", flush=True)

    def undo(self, text: str) -> None:
        """Undo the last injected text by sending backspaces."""
        if self._method in ("xdotool", "clipboard", "wl-clipboard"):
            count = len(text)
            if count == 0:
                return
            try:
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers",
                     "--repeat", str(count), "BackSpace"],
                    timeout=10,
                )
            except Exception as e:
                logger.error("Undo failed: %s", e)
