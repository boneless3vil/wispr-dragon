"""Inject transcribed text into the active window."""

import logging
import subprocess
import shutil

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

    @property
    def method(self) -> str:
        """The active injection backend after auto-detection."""
        return self._method

    def _detect_method(self) -> str:
        if shutil.which("xdotool"):
            return "xdotool"
        if shutil.which("xclip"):
            return "clipboard"
        if shutil.which("wl-copy"):
            return "wl-clipboard"
        # WSL fallback: send text to the Windows clipboard via the built-in
        # clip.exe interop binary. User pastes manually with Ctrl+V.
        if shutil.which("clip.exe"):
            return "clip.exe"
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
        elif self._method == "clip.exe":
            self._inject_clip_exe(text)
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

    def _inject_clip_exe(self, text: str) -> None:
        """Pipe text to Windows clipboard via the clip.exe interop binary.

        Note: this only puts text on the clipboard; the user must press Ctrl+V
        in their target Windows app to paste. Auto-paste from WSL into Windows
        requires a Windows-side companion process and is out of scope here.

        clip.exe expects UTF-16 LE on stdin to handle non-ASCII reliably; UTF-8
        works for ASCII-only text but mangles things like curly quotes.
        """
        try:
            proc = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-16-le"))
            logger.info("Text copied to Windows clipboard — press Ctrl+V to paste")
        except FileNotFoundError:
            logger.error("clip.exe not found, falling back to print")
            print(text, end="", flush=True)
        except Exception as e:
            logger.error("clip.exe injection failed: %s", e)
            print(text, end="", flush=True)

    def undo(self, text: str) -> None:
        """Undo the last injected text by sending backspaces.

        Handles newlines specially - sends Delete key for newlines,
        BackSpace for regular characters.
        """
        if self._method in ("xdotool", "clipboard", "wl-clipboard"):
            if not text:
                return

            try:
                newline_count = text.count('\n')
                regular_count = len(text) - newline_count

                keys = []
                if regular_count > 0:
                    keys.extend(["--repeat", str(regular_count), "BackSpace"])
                if newline_count > 0:
                    keys.extend(["--repeat", str(newline_count), "Delete"])

                if keys:
                    subprocess.run(
                        ["xdotool", "key", "--clearmodifiers"] + keys,
                        timeout=10,
                    )
            except Exception as e:
                logger.error("Undo failed: %s", e)
