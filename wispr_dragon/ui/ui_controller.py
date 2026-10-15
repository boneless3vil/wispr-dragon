"""Main UI controller — orchestrates dictation box with audio/transcription threads."""

import logging
import sys
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class UIController:
    """Manages the dictation box UI with background audio/transcription threads.

    Coordinates:
    - DictationBox (PyQt6 UI thread)
    - AudioWorker (audio capture thread)
    - TranscriptionWorker (transcription thread)
    - Command matching and confirmation dialogs
    """

    def __init__(self, config, user_dir: Path, engine, vad=None, post_processor=None,
                 text_injector=None, dictionary=None):
        """Initialize UI controller.

        Args:
            config: Config object
            user_dir: User config directory (~/.wispr_dragon)
            engine: TranscriptionEngine instance (already loaded)
            vad: VoiceActivityDetector instance (already loaded). Required for
                segmented transcription — without it the worker has no way to
                decide when to call the engine.
            post_processor: PostProcessor for text correction (optional)
            text_injector: TextInjector for posting text (optional)
            dictionary: UserDictionary, used by the correction window (optional)
        """
        self.config = config
        self.user_dir = user_dir
        self.engine = engine
        self.vad = vad
        self.post_processor = post_processor
        self.text_injector = text_injector
        self.dictionary = dictionary

        self.dictation_box = None
        self.audio_worker = None
        self.transcription_worker = None
        self.audio_thread = None
        self.transcription_thread = None
        self.is_running = False
        # Set by stop(); the audio thread parks on it once the stream is open.
        self._stop_event = threading.Event()

        # Modes/commands pipeline — built in initialize() once the box exists,
        # since the action handlers operate on the box. None until then; when
        # None the box behaves as a plain transcribe->display surface.
        self.mode_mgr = None
        self.orchestrator = None
        self.macro_runner = None

        # Single source of truth for the OFF/STANDBY/HOT mic indicator.
        from .mic_state import MicStateController
        self.mic_state = MicStateController()

        # System tray — provides the Commands & Vocabulary browser entry point
        # and a mic-state indicator. Created in start(); None if unavailable.
        self.tray = None

    def initialize(self) -> bool:
        """Initialize UI and workers.

        Returns:
            True on success
        """
        try:
            from .dictation_box import DictationBox
            from .audio_worker import AudioWorker
            from .transcription_worker import TranscriptionWorker

            # Create workers
            self.audio_worker = AudioWorker(
                self.config.audio,
                on_audio_chunk=self._on_audio_chunk,
                on_error=self._on_error,
            )

            self.transcription_worker = TranscriptionWorker(
                self.engine,
                vad=self.vad,
                # No post-processing in the worker: the orchestrator does it,
                # mode-aware (or _on_transcription, when there's none). Doing it
                # here too formatted every segment twice — which, e.g., ate the
                # "cap" in spelling mode and fed command matching formatted text.
                post_processor=None,
                hotword_mgr=self._build_hotword_manager(),
                on_transcription=self._on_transcription,
                on_error=self._on_error,
                language=self.config.engine.language,
                beam_size=self.config.engine.beam_size,
            )

            # Create UI
            self.dictation_box = DictationBox(
                self.config,
                self.user_dir,
                on_text_ready=self._on_text_ready,
                on_toggle_mic=self._toggle_mic,
                on_cancel=self.stop,
            )

            # Warn up front if the active injection backend can't reach native
            # Windows apps — the #1 source of "Post does nothing" confusion.
            self._apply_backend_hint()

            # Build the modes/commands pipeline now that the box exists, so the
            # box honors "scratch that", "correct that", command mode and macros
            # — the same behavior as the headless loop. Requires a post-processor.
            if self.post_processor is not None:
                self._build_orchestrator()

            logger.info("UI initialized successfully")
            return True

        except ImportError as e:
            logger.error("PyQt6 not available: %s", e)
            return False
        except Exception as e:
            logger.error("UI initialization failed: %s", e)
            return False

    def start(self) -> bool:
        """Start dictation session (show UI + begin recording).

        Returns:
            True on success
        """
        if not self.initialize():
            return False

        try:
            self.is_running = True
            self._stop_event.clear()

            # Start audio worker thread
            self.audio_thread = threading.Thread(
                target=self._audio_thread_main,
                daemon=True,
            )
            self.audio_thread.start()

            # Start transcription worker thread
            self.transcription_thread = threading.Thread(
                target=self._transcription_thread_main,
                daemon=True,
            )
            self.transcription_thread.start()

            # Show UI (non-blocking — caller drives the Qt event loop via app.exec())
            self.dictation_box.show()
            # Tray before set_capturing so its observer catches the HOT transition.
            self._setup_tray()
            self.mic_state.set_capturing(True)
            logger.info("Dictation session started")
            return True

        except Exception as e:
            logger.error("Failed to start dictation: %s", e)
            self.stop()
            return False

    def stop(self):
        """Stop dictation session (close UI + stop threads). Idempotent."""
        self.is_running = False
        self._stop_event.set()
        self.mic_state.set_capturing(False)

        if self.tray and self.tray.tray_widget:
            try:
                self.tray.tray_widget.hide()
            except Exception as e:
                logger.warning("Error hiding tray: %s", e)

        if self.dictation_box:
            try:
                self.dictation_box.close()
            except Exception as e:
                logger.warning("Error closing dictation box: %s", e)

        if self.audio_worker:
            self.audio_worker.stop_recording()
            self.audio_worker.cleanup()

        if self.transcription_worker:
            self.transcription_worker.stop()
            self.transcription_worker.reset()

        # No join: stop() runs on the GUI thread (Post / Cancel), and joining
        # froze it for up to 4 s while an in-flight transcription finished. Both
        # threads are daemons that exit on their own once signalled; a segment
        # that lands afterwards is dropped by _on_transcription's is_running check.
        logger.info("Dictation session stopped")

    def _audio_thread_main(self):
        """Open the mic stream off the GUI thread, then park until stop().

        Audio is delivered on PortAudio's own callback thread, so this thread
        does no work once the stream is open. It parks (on an Event — no
        polling) rather than exiting so the thread that opened the stream
        outlives it, as before: some host APIs may tie state to the opening
        thread (e.g. COM under WASAPI), and letting it exit early hasn't been
        verified on every platform.
        """
        try:
            if self.audio_worker.start_recording():
                self._stop_event.wait()
        except Exception as e:
            logger.error("Audio thread error: %s", e)
            if self.dictation_box:
                self.dictation_box.show_status(f"Error: {e}")

    def _transcription_thread_main(self):
        """Drive the transcription worker loop in a dedicated thread."""
        try:
            if self.transcription_worker:
                self.transcription_worker.run()
        except Exception as e:
            logger.error("Transcription thread error: %s", e)
            if self.dictation_box:
                self.dictation_box.show_status(f"Error: {e}")

    def _on_audio_chunk(self, chunk):
        """Callback from AudioWorker when audio chunk is ready.

        Runs on the PortAudio callback thread. Must be fast — just enqueue.
        Heavy work (VAD + transcription) happens in the transcription thread.
        """
        if self.transcription_worker:
            self.transcription_worker.enqueue_chunk(chunk)

    def _on_transcription(self, live: str, final: Optional[str]):
        """Callback from TranscriptionWorker when transcription updates.

        Runs on the transcription worker thread. Live hypotheses go straight to
        the box's gray preview; finalized segments are routed through the
        orchestrator so commands/mode switches/macros fire and only dictation
        text reaches the box.
        """
        # A segment can finish after Post/Cancel ended the session; drop it so it
        # can't fire a keystroke or macro into whatever window has focus now.
        if not self.is_running or not self.dictation_box:
            return
        try:
            if final:
                if self.orchestrator is None:
                    if self.post_processor is not None:
                        final = self.post_processor.process(final)
                    self.dictation_box.update_transcription("", final)
                    return
                outcome = self.orchestrator.handle_transcript(final)
                if outcome.has_text:
                    self.dictation_box.update_transcription("", outcome.text)
                else:
                    # Command/mode switch consumed it — clear the live preview.
                    self.dictation_box.update_transcription("", "")
            else:
                self.dictation_box.update_transcription(live, "")
        except Exception as e:
            logger.error("Error handling transcription: %s", e)

    def _toggle_mic(self, paused: bool) -> None:
        """Mic button callback — gate audio capture and reflect it in mic state."""
        from ..modes.mode_manager import Mode

        if self.audio_worker:
            self.audio_worker.set_paused(paused)
        # Paused => mic gated off (gray dot). Resuming reflects the mode as it is
        # *now*, not as it was at pause time: segments already in the pipeline
        # keep being processed while paused, so a "go to sleep" / "wake up" may
        # have changed it since (set_asleep is ignored while OFF).
        if paused:
            self.mic_state.set_capturing(False)
        else:
            self.mic_state.set_capturing(True)
            asleep = self.mode_mgr is not None and self.mode_mgr.mode == Mode.SLEEP
            self.mic_state.set_asleep(asleep)

    def _build_hotword_manager(self):
        """Vocabulary bias for the engine (initial_prompt / hotwords), like the server.

        Built from the post-processor's dictionary so learned corrections and
        custom words bias recognition as well as fix it up afterwards. None when
        there's no dictionary to draw from.
        """
        dictionary = getattr(self.post_processor, "dictionary", None)
        if dictionary is None:
            dictionary = self.dictionary
        if dictionary is None:
            return None
        from ..correction.hotwords import HotwordManager
        return HotwordManager(dictionary, self.config.correction.max_hotwords)

    def _apply_backend_hint(self) -> None:
        """Surface a hint in the box when the injection backend has caveats."""
        if not self.dictation_box or not self.text_injector:
            return
        method = getattr(self.text_injector, "method", None)
        if method in ("xdotool", "clipboard", "wl-clipboard"):
            self.dictation_box.set_backend_hint(
                "Types into Linux/WSLg windows only — native Windows apps "
                "(PowerShell, Terminal, Word, browsers) can't be reached from "
                "here. Use the Windows client for those, or run with "
                "--inject-method clip.exe to copy + paste manually."
            )
        elif method == "clip.exe":
            self.dictation_box.set_backend_hint(
                "Post copies the text to the Windows clipboard — press Ctrl+V "
                "in your target app to paste it."
            )

    def _build_orchestrator(self):
        """Construct the ModeManager + orchestrator and register UI handlers."""
        from ..modes.mode_manager import ModeManager
        from ..modes.orchestrator import DictationOrchestrator
        from ..modes.command_mode import load_commands
        from ..macros.macro_runner import MacroRunner

        from ..modes.mode_manager import Mode
        from ..modes.transforms import build_transformers

        # Pass the in-memory security config so --dictation-only and a --config
        # file apply here, not just whatever ~/.wispr_dragon/config.yaml says.
        self.macro_runner = MacroRunner(
            self.user_dir,
            text_injector=self.text_injector,
            security_cfg=self.config.security,
        )
        self.mode_mgr = ModeManager(
            macro_runner=self.macro_runner,
            dictation_only=self.config.security.dictation_only,
        )
        load_commands(user_dir=self.user_dir)
        self._register_mode_handlers()
        self.orchestrator = DictationOrchestrator(
            self.post_processor, self.mode_mgr, transformers=build_transformers()
        )

        # Deferred GUI-thread actions emitted from the worker thread. The box
        # (a QObject on the GUI thread) receives the queued signal and invokes
        # this handler on the GUI thread, so QDialogs are constructed there.
        self.dictation_box.set_ui_action_handler(self._on_ui_action)

        # Mic-state wiring: the box observes state changes; sleep/wake mode
        # transitions drive STANDBY <-> HOT. The mode callback fires on the worker
        # thread, so every observer must marshal to the GUI thread itself (the
        # box's and the tray's set_mic_state both do).
        self.mic_state.add_observer(self.dictation_box.set_mic_state)
        self.mode_mgr.set_mode_change_callback(
            lambda mode: self.mic_state.set_asleep(mode == Mode.SLEEP)
        )

    def _register_mode_handlers(self):
        """Register UI-specific command handlers on the ModeManager.

        These run on the transcription worker thread. Anything touching Qt
        widgets must be deferred to the GUI thread via the box's signals.
        """
        box = self.dictation_box

        def handle_undo(undone_text):
            # Nothing is injected until Post, so undo just drops the on-screen
            # segment rather than rewinding an injected stream.
            box.remove_last_segment()

        def handle_correction(text, args=None):
            box.ui_action_requested.emit("correct", None)

        def handle_keystroke(text, args=None):
            self._send_keystroke(args.get("keys", "") if args else "")

        def handle_macro(text, args=None):
            box.ui_action_requested.emit(
                "macro", {"macro": args.get("macro") if args else None, "text": text}
            )

        self.mode_mgr.register_handler("undo_last", handle_undo)
        self.mode_mgr.register_handler("open_correction_window", handle_correction)
        self.mode_mgr.register_handler("keystroke", handle_keystroke)
        self.mode_mgr.register_handler("macro", handle_macro)

    def _on_ui_action(self, action: str, payload):
        """GUI-thread dispatcher for deferred actions from the worker thread."""
        try:
            if action == "correct":
                self._open_correction()
            elif action == "macro":
                self._run_macro(payload)
        except Exception as e:
            logger.error("UI action '%s' failed: %s", action, e)

    def _open_correction(self):
        """Open the correction window on the last segment (GUI thread)."""
        target = self.dictation_box.last_segment()
        if not target:
            self.dictation_box.show_status("Nothing to correct")
            return
        if self.dictionary is None:
            return
        from .correction_window import CorrectionWindow
        window = CorrectionWindow(self.dictionary)
        corrected = window.show(target)
        if corrected and corrected != target:
            self.dictation_box.replace_last_segment(corrected)

    def _setup_tray(self):
        """Create the system tray icon and wire its mic indicator + browser entry.

        No-op if PyQt6 or the QApplication is unavailable (e.g. headless).
        """
        try:
            from PyQt6.QtWidgets import QApplication

            from .system_tray import SystemTray
        except ImportError:
            return

        def on_quit():
            app = QApplication.instance()
            if app:
                app.quit()

        self.tray = SystemTray(
            self.dictation_box,
            on_quit=on_quit,
            on_toggle=self.dictation_box.toggle_mic,
            on_open_browser=self.open_command_vocab_browser,
            # On macOS a click on the status item opens the menu *and* reports
            # Trigger, so click-to-toggle would flip the mic on every menu open.
            # There the menu's toggle item is the way in.
            toggle_on_click=sys.platform != "darwin",
        )
        if self.tray.setup():
            # Drive the tray indicator from the same single source of truth.
            self.mic_state.add_observer(self.tray.set_mic_state)
            self.tray.set_mic_state(self.mic_state.state)
        else:
            self.tray = None

    def open_command_vocab_browser(self):
        """Open the Dragon-style Commands & Vocabulary browser (GUI thread).

        Constructs the MacroEditor with this controller's user_dir and
        UserDictionary so the Commands tab edits ~/.wispr_dragon/macros and the
        Vocabulary tab is backed by the shared dictionary. Opening the browser
        never trusts or executes a macro — trust stays at execution time.
        """
        from .macro_editor import MacroEditor

        editor = MacroEditor(
            self.user_dir,
            # The box is a QObject wrapper; the dialog's parent must be a widget.
            parent=self.dictation_box.window if self.dictation_box else None,
            dictionary=self.dictionary,
        )
        editor.show()  # modal — returns once the browser is closed
        # Apply command edits now rather than on the next restart.
        if self.macro_runner is not None:
            self.macro_runner.reload_macros()

    def _run_macro(self, payload):
        """Confirm (in dictation mode) and execute a matched macro (GUI thread)."""
        from ..modes.mode_manager import Mode

        macro = (payload or {}).get("macro")
        if not macro or not self.macro_runner:
            return
        text = (payload or {}).get("text", "")
        captured = macro.pop("_captured_args", None)

        # In dictation mode, confirm before running (same trust flow as the
        # headless path). On "no" the box keeps the spoken phrase as dictation;
        # the headless loop can't (ModeManager discards handler return values).
        if self.mode_mgr.mode == Mode.DICTATION and not self.config.security.dictation_only:
            from .confirm_command import ConfirmationDialog

            dialog = ConfirmationDialog(self.user_dir)
            action = macro.get("action", "unknown")
            target = macro.get("program") or macro.get("script")
            choice = dialog.show_and_ask(text, macro.get("trigger", ""), action, target)
            if choice == "no":
                # User would rather type the trigger phrase as dictation. The
                # orchestrator only records undo history for text it emits, so
                # record this segment too or "scratch that" drifts from the box.
                self.dictation_box.update_transcription("", text)
                self.mode_mgr.record_output(text)
                return
            elif choice == "trust" and target:
                dialog.trust_manifest.add_trust(target, is_script=(action == "python_script"))
            elif choice is None:
                return
            # "yes" -> fall through to execute

        self.macro_runner.execute(macro, captured)

    def _send_keystroke(self, keys: str):
        """Send a validated keystroke, dispatching per platform.

        ``keys`` is an xdotool-style chord: modifiers and a final key joined by
        ``+`` (e.g. ``ctrl+s``, ``alt+Tab``, ``Return``, ``a``). Platform paths:

        * Linux (``linux``): xdotool, the existing X11/WSLg path (unchanged).
          Wayland support via ydotool is a TODO (consistent with CLAUDE.md;
          ydotool needs uinput permission, mirroring the injector setup notes).
        * Windows (``win32``) / macOS (``darwin``): pynput, already a client
          dependency (see ``client/hotkey.py``), so we don't shell out to
          xdotool which doesn't exist there. macOS additionally needs
          Accessibility permission for synthesized input to land.
        """
        import re

        if not keys or not re.match(r"^[a-zA-Z0-9+\-_]+$", keys):
            logger.error("Invalid keystroke pattern: %s", keys)
            return

        if sys.platform == "linux":
            self._send_keystroke_xdotool(keys)
        else:
            # win32 + darwin both route through pynput.
            self._send_keystroke_pynput(keys)

    def _send_keystroke_xdotool(self, keys: str):
        """Linux/WSLg X11 keystroke via xdotool (TODO: ydotool for Wayland)."""
        import subprocess

        try:
            subprocess.run(["xdotool", "key", "--clearmodifiers", keys], timeout=2)
        except FileNotFoundError:
            logger.error("xdotool not found")
        except subprocess.TimeoutExpired:
            logger.error("Keystroke command timed out")

    # xdotool key names -> pynput special keys. Bare single characters and
    # digits aren't listed: they map to KeyCode.from_char directly. Names not
    # found here and longer than one char can't be sent and are warned about.
    _PYNPUT_KEY_MAP = {
        "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
        "super": "cmd", "meta": "cmd", "cmd": "cmd", "win": "cmd",
        "return": "enter", "enter": "enter", "tab": "tab", "escape": "esc",
        "esc": "esc", "space": "space", "backspace": "backspace",
        "delete": "delete", "home": "home", "end": "end", "page_up": "page_up",
        "page_down": "page_down", "up": "up", "down": "down", "left": "left",
        "right": "right",
        **{f"f{n}": f"f{n}" for n in range(1, 13)},
    }

    def _send_keystroke_pynput(self, keys: str):
        """Windows/macOS keystroke via pynput (no native key tool to shell to)."""
        try:
            from pynput import keyboard  # lazy: keep module importable on CI
        except ImportError:
            logger.error("pynput unavailable; cannot send keystroke %r", keys)
            return

        def resolve(token: str):
            low = token.lower()
            mapped = self._PYNPUT_KEY_MAP.get(low)
            if mapped is not None:
                return getattr(keyboard.Key, mapped)
            if len(token) == 1:
                return keyboard.KeyCode.from_char(token)
            return None

        # The last token is the actual key; everything before it is a modifier.
        parts = keys.split("+")
        resolved = [resolve(t) for t in parts]
        if any(r is None for r in resolved):
            unmapped = [t for t, r in zip(parts, resolved) if r is None]
            logger.warning(
                "Cannot map keystroke %r on %s (unmapped: %s)",
                keys, sys.platform, ", ".join(unmapped),
            )
            return

        modifiers = resolved[:-1]
        main_key = resolved[-1]
        controller = keyboard.Controller()
        try:
            for mod in modifiers:
                controller.press(mod)
            controller.press(main_key)
            controller.release(main_key)
            for mod in reversed(modifiers):
                controller.release(mod)
        except Exception as e:
            logger.error("pynput keystroke %r failed: %s", keys, e)

    def _on_text_ready(self, text: str):
        """Callback from DictationBox when user clicks Post."""
        # Inject text into active window
        if self.text_injector:
            try:
                self.text_injector.inject(text)
                logger.info("Text injected: %d characters", len(text))
            except Exception as e:
                logger.error("Failed to inject text: %s", e)
                if self.dictation_box:
                    self.dictation_box.show_status(f"Error: {e}")

        # Stop recording
        self.stop()

    def _on_error(self, error_msg: str):
        """Callback when audio/transcription worker encounters an error."""
        logger.error("Worker error: %s", error_msg)
        if self.dictation_box:
            try:
                self.dictation_box.show_status(f"Error: {error_msg}")
            except Exception as e:
                logger.warning("Error updating status: %s", e)
