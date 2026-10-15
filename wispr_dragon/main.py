"""Wispr-Dragon main entry point."""

import argparse
import asyncio
import dataclasses
import getpass
import logging
import re
import signal
import subprocess
import sys
from pathlib import Path

from .config import Config
from .correction.dictionary import UserDictionary
from .correction.hotwords import HotwordManager
from .correction.post_processor import PostProcessor
from .engine import create_engine
from .macros.macro_runner import MacroRunner
from .macros.security import SecurityPolicy, is_safe_script_name
from .modes.mode_manager import ModeManager, Mode
from .output.text_injector import TextInjector

logger = logging.getLogger("wispr_dragon")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _security_policy(config: Config) -> SecurityPolicy:
    """SecurityPolicy for the loaded config (honours --config and CLI flags)."""
    return SecurityPolicy(config.user_dir, security_cfg=config.security)


def _confirm_admin_password(security: SecurityPolicy) -> bool:
    """Prompt for the current admin password; True if it matches the lock."""
    password = getpass.getpass("Admin lock is active. Enter admin password: ")
    if security.verify_admin_password(password):
        return True
    print("✗ Admin password incorrect")
    return False


def _handle_sign_script(script_name: str, config: Config) -> int:
    """Sign a Python script (requires the admin password while locked)."""
    if not is_safe_script_name(script_name):
        print(f"✗ Script must be a bare file name inside {config.user_dir / 'scripts'}: {script_name}")
        return 1

    security = _security_policy(config)
    if security.is_locked() and not _confirm_admin_password(security):
        return 1

    script_path = config.user_dir / "scripts" / script_name
    if security.sign_script(script_path):
        print(f"✓ Script signed: {script_name}")
        return 0
    else:
        print(f"✗ Failed to sign script: {script_name}")
        return 1


def _handle_admin_lock(config: Config) -> int:
    """Enable admin lock with password.

    The lock pins the policy currently in force (config + CLI flags + any
    existing lock), so locking can only keep or tighten it, never loosen it.
    Replacing an existing lock requires its password.
    """
    import bcrypt

    security = _security_policy(config)
    if security.is_locked() and not _confirm_admin_password(security):
        return 1
    policy = security.effective_policy()

    password = getpass.getpass("Enter admin password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("✗ Passwords do not match")
        return 1

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    if security.set_admin_lock(password_hash, policy):
        print("✓ Admin lock enabled")
        return 0
    else:
        print("✗ Failed to set admin lock")
        return 1


def _handle_admin_unlock(config: Config) -> int:
    """Disable admin lock."""
    password = getpass.getpass("Enter admin password: ")

    # Pass the plaintext password — remove_admin_lock verifies it against the
    # stored hash with bcrypt.checkpw. Hashing here would produce a fresh salt
    # that could never match the stored hash.
    security = _security_policy(config)
    if security.remove_admin_lock(password):
        print("✓ Admin lock removed")
        return 0
    else:
        print("✗ Admin password incorrect")
        return 1


def _handle_security_status(config: Config) -> int:
    """Show current security policy."""
    security = _security_policy(config)
    print("\n=== Wispr-Dragon Security Status ===\n")

    if security.is_locked():
        print("Status: LOCKED (password-protected)")
    else:
        print("Status: UNLOCKED")

    print("\nPolicy Settings:")
    print(f"  Allow Python scripts:    {security.allows_python_scripts()}")
    print(f"  Allow YAML macros:       {security.allows_yaml_macros()}")
    print(f"  Allow program launch:    {security.allows_program_launch()}")
    print(f"  Dictation-only mode:     {security.is_dictation_only()}")
    print()

    return 0


def _handle_clear_trust(user_dir) -> int:
    """Clear trusted programs/scripts."""
    trust_file = user_dir / "trusted.json"
    if trust_file.exists():
        trust_file.unlink()
        print("✓ Trusted programs/scripts cleared")
        return 0
    else:
        print("✗ No trust manifest found")
        return 1


def _validate_keystroke(keys: str) -> bool:
    """Validate keystroke string against whitelist.

    Allowed: alphanumeric, +, -, _, and valid xdotool key names.
    """
    if not keys:
        return False
    return bool(re.match(r"^[a-zA-Z0-9+\-_]+$", keys))


def _detect_lan_ip() -> str:
    """Best-effort LAN IP for the host, for the client-setup hint.

    Opens a throwaway UDP socket toward a public address (no packets sent) and
    reads back the local endpoint the OS would route through. Returns a
    placeholder if anything goes wrong — never raises.
    """
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "<this-host-ip>"


def format_client_setup(api_key: str, host_ip: str, port: int, generated: bool) -> str:
    """Render a copy-paste-friendly client-setup block for ``--print-key``.

    Pure/no-IO so it can be unit-tested. Keeps a legacy ``API Key:`` /
    ``Generated API Key:`` line (some scripts grep for it) and adds a ready-to-
    paste ``config.json`` snippet plus the server URL the client should use.
    """
    url = f"ws://{host_ip}:{port}"
    saved_note = " (generated, saved to server config.yaml)" if generated else ""
    return (
        "=== Wispr Dragon — Client Setup ===\n"
        f"API Key: {api_key}{saved_note}\n"
        f'Server URL: {url}   ("localhost" only works if the client runs on this machine)\n'
        "\n"
        "Paste into the Windows client's config.json\n"
        "(%LOCALAPPDATA%\\WisprDragon\\config.json), or use the client's Settings dialog:\n"
        "\n"
        "{\n"
        f'  "server_url": "{url}",\n'
        f'  "api_key": "{api_key}"\n'
        "}"
    )


def _handle_server_mode(
    config: Config, print_key: bool = False, config_path: Path | None = None
) -> int:
    """Launch WebSocket server for speech-to-text service.

    ``config_path`` is the ``--config`` file (None = default); a generated API
    key is saved back there.
    """
    try:
        from wispr_dragon.server.pipeline_runner import PipelineRunner
        from wispr_dragon.server.websocket_server import WebSocketServer

        if print_key:
            generated = not config.server.api_key
            if generated:
                import secrets
                config.server.api_key = secrets.token_hex(16)
                config.save(config_path)
            print(
                format_client_setup(
                    config.server.api_key,
                    _detect_lan_ip(),
                    config.server.port,
                    generated,
                )
            )
            return 0

        logger.info("Starting server mode...")

        pipeline = PipelineRunner(config)
        if not pipeline.load(vad_enabled=True):
            logger.error("Failed to load pipeline")
            return 1

        server = WebSocketServer(config, pipeline)

        try:
            asyncio.run(server.start())
            return 0
        except KeyboardInterrupt:
            logger.info("Server stopped")
            return 0

    except ImportError as e:
        logger.error("WebSocket dependencies not available: %s", e)
        print("Install websockets: pip install websockets")
        return 1
    except Exception as e:
        logger.error("Server mode failed: %s", e)
        return 1


def _handle_ui_mode(config: Config, inject_method: str = "auto") -> int:
    """Launch floating dictation box UI."""
    try:
        from PyQt6.QtWidgets import QApplication

        from .ui.ui_controller import UIController

        app = QApplication.instance() or QApplication(sys.argv)

        # App-level icon (fallback for any window that doesn't set its own).
        from .icons import mic_off_icon
        _app_icon = mic_off_icon()
        if _app_icon is not None:
            app.setWindowIcon(_app_icon)

        logger.info("Starting UI mode...")
        dictionary = UserDictionary()
        post_processor = PostProcessor(
            dictionary,
            fuzzy_threshold=config.correction.fuzzy_match_score,
            auto_apply_threshold=config.correction.auto_apply_threshold,
        )
        text_injector = TextInjector(method=inject_method)
        logger.info("Text injection method: %s", text_injector.method)

        engine = create_engine(config)
        logger.info("Loading model: %s", config.engine.model_size)
        engine.load_model(
            config.engine.model_size,
            device=config.engine.device,
            compute_type=config.engine.compute_type,
        )
        logger.info("Model loaded successfully")

        # Load VAD so the worker can segment speech rather than re-transcribing
        # a growing buffer every 100ms.
        from .audio.vad import VoiceActivityDetector
        vad = VoiceActivityDetector(
            sample_rate=config.audio.sample_rate,
            threshold=config.audio.vad_threshold,
            silence_duration_ms=config.audio.silence_duration_ms,
            min_speech_duration_ms=config.audio.min_speech_duration_ms,
        )
        vad.load()
        logger.info("VAD loaded")

        controller = UIController(
            config,
            config.user_dir,
            engine,
            vad=vad,
            post_processor=post_processor,
            text_injector=text_injector,
            dictionary=dictionary,
        )

        if not controller.start():
            logger.error("Failed to start UI")
            return 1

        exit_code = app.exec()
        controller.stop()
        return exit_code

    except ImportError as e:
        logger.error("PyQt6 not available: %s", e)
        return 1
    except Exception as e:
        logger.error("UI mode failed: %s", e)
        return 1




def create_audio_source(config: Config):
    """Create the appropriate audio capture source."""
    if config.audio.source == "network":
        from .audio.capture import NetworkAudioCapture
        return NetworkAudioCapture(
            host=config.audio.network_host,
            port=config.audio.network_port,
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )
    else:
        from .audio.capture import AudioCapture
        return AudioCapture(
            sample_rate=config.audio.sample_rate,
            channels=config.audio.channels,
        )


def _apply_cli_overrides(parser: argparse.ArgumentParser, args, config: Config) -> None:
    """Apply engine/security CLI overrides through the dataclasses so their
    ``__post_init__`` validation runs; invalid values are an argparse error."""
    engine_overrides = {}
    if args.model:
        engine_overrides["model_size"] = args.model
    if args.device:
        engine_overrides["device"] = args.device
    if args.compute_type:
        engine_overrides["compute_type"] = args.compute_type
    if args.beam_size is not None:
        engine_overrides["beam_size"] = args.beam_size
    if engine_overrides:
        try:
            config.engine = dataclasses.replace(config.engine, **engine_overrides)
        except ValueError as e:
            parser.error(str(e))
    if args.dictation_only:
        config.security = dataclasses.replace(config.security, dictation_only=True)


def _register_headless_handlers(mode_mgr, injector, macro_runner, config: Config) -> None:
    """Register the headless loop's command handlers on ``mode_mgr``."""

    def handle_undo(text):
        injector.undo(text)

    def handle_correction(text, args=None):
        # The correction window is a Qt dialog; the headless loop has no Qt
        # event loop, so "correct that" is acknowledged but not actionable.
        logger.info("Correction is not available in headless mode; run with --ui to use it")

    def handle_keystroke(text, args=None):
        keys = args.get("keys", "") if args else ""
        if not keys:
            return
        if not _validate_keystroke(keys):
            logger.error("Invalid keystroke pattern: %s", keys)
            return
        try:
            subprocess.run(["xdotool", "key", "--clearmodifiers", keys], timeout=2)
        except FileNotFoundError:
            logger.error("xdotool not found")
        except subprocess.TimeoutExpired:
            logger.error("Keystroke command timed out")

    def handle_macro(text, args=None):
        """Handler for voice-triggered macros."""
        if not args or "macro" not in args:
            return

        macro = args["macro"]
        captured_args = macro.pop("_captured_args", None)

        # If in dictation mode, show confirmation dialog
        if mode_mgr.mode == Mode.DICTATION and not config.security.dictation_only:
            from .ui.confirm_command import ConfirmationDialog

            dialog = ConfirmationDialog(config.user_dir)
            action = macro.get("action", "unknown")
            target = macro.get("program") or macro.get("script")

            choice = dialog.show_and_ask(text, macro.get("trigger", ""), action, target)

            if choice == "no":
                # ModeManager discards handler return values, so the phrase
                # can't be re-emitted as dictation from here.
                return
            elif choice == "trust" and target:
                # Add to trust list and execute
                is_script = action == "python_script"
                dialog.trust_manifest.add_trust(target, is_script=is_script)
                macro_runner.execute(macro, captured_args)
                return
            elif choice is None:
                # User cancelled
                return
            # choice == "yes": fall through to execute

        success = macro_runner.execute(macro, captured_args)
        logger.debug("Macro execution: %s", "success" if success else "failed")

    mode_mgr.register_handler("undo_last", handle_undo)
    mode_mgr.register_handler("open_correction_window", handle_correction)
    mode_mgr.register_handler("keystroke", handle_keystroke)
    mode_mgr.register_handler("macro", handle_macro)


def _build_headless_pipeline(config: Config, post_processor, injector):
    """Build the headless ModeManager + orchestrator.

    Security settings come from the loaded config (so ``--config`` and
    ``--dictation-only`` apply). The orchestrator doesn't record undo entries:
    :func:`_emit_headless` records exactly what it injects.
    """
    from .modes.command_mode import load_commands
    from .modes.orchestrator import DictationOrchestrator
    from .modes.transforms import build_transformers

    macro_runner = MacroRunner(
        config.user_dir, text_injector=injector, security_cfg=config.security
    )
    mode_mgr = ModeManager(
        macro_runner=macro_runner, dictation_only=config.security.dictation_only
    )
    load_commands(user_dir=config.user_dir)
    _register_headless_handlers(mode_mgr, injector, macro_runner, config)

    # Shared text pipeline (post-process -> mode/command dispatch -> transform),
    # reused by the floating dictation box so the two paths don't drift.
    orchestrator = DictationOrchestrator(
        post_processor, mode_mgr, transformers=build_transformers(), record_outputs=False
    )
    return mode_mgr, orchestrator


def _emit_headless(outcome, injector, mode_mgr) -> None:
    """Inject one outcome's text (plus a separator space) and record exactly
    the injected string so "scratch that" removes all of it."""
    if not outcome.has_text:
        return
    emitted = outcome.text + " "
    injector.inject(emitted)
    mode_mgr.record_output(emitted)
    logger.debug("Output: %s", outcome.text)


def main():
    parser = argparse.ArgumentParser(description="Wispr-Dragon Speech Recognition")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--model", type=str, help="Override model size (e.g., small.en, medium.en, large-v3)")
    parser.add_argument("--device", type=str, help="Override device (cuda, cpu)")
    parser.add_argument(
        "--compute-type",
        choices=["auto", "float16", "int8", "int8_float16", "bfloat16", "float32"],
        help="Override compute type. int8_float16 halves VRAM use vs float16 — try it if a larger model thrashes.",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        help="Override beam size. Higher = more accurate but slower (default 10).",
    )
    parser.add_argument("--no-vad", action="store_true", help="Disable voice activity detection")
    parser.add_argument("--dictation-only", action="store_true", help="Enable dictation-only mode (no macros)")

    # Security admin commands
    parser.add_argument("--sign-script", type=str, metavar="SCRIPT", help="Sign a Python script")
    parser.add_argument("--admin-lock", action="store_true", help="Enable admin lock with password")
    parser.add_argument("--admin-unlock", action="store_true", help="Disable admin lock (requires password)")
    parser.add_argument("--security-status", action="store_true", help="Show current security policy")
    parser.add_argument("--clear-trust", action="store_true", help="Clear trusted programs/scripts")

    # Server mode
    parser.add_argument("--server", action="store_true", help="Run as WebSocket server for remote clients")
    parser.add_argument("--print-key", action="store_true", help="Print API key and exit")

    # UI mode
    parser.add_argument("--ui", action="store_true", help="Launch floating dictation box UI")

    # Text injection backend (auto-detected by default)
    parser.add_argument(
        "--inject-method",
        choices=["auto", "xdotool", "clipboard", "wl-clipboard", "clip.exe", "print"],
        default="auto",
        help=(
            "Override text injection backend. 'xdotool' types into the focused X11/WSLg "
            "window (Linux apps). 'clip.exe' copies to the Windows clipboard via WSL "
            "interop (you press Ctrl+V to paste into a Windows app)."
        ),
    )

    args = parser.parse_args()
    if args.print_key and not args.server:
        parser.error("--print-key requires --server")

    # Load config first
    config_path = Path(args.config) if args.config else None
    config = Config.load(config_path)

    # Apply (validated) CLI overrides before anything dispatches, so --server,
    # --ui and the admin commands all see them. --dictation-only only ever
    # tightens policy, so it applies to --admin-lock / --security-status too.
    _apply_cli_overrides(parser, args, config)

    # Handle admin commands (exit after executing)
    if args.sign_script:
        return _handle_sign_script(args.sign_script, config)
    if args.admin_lock:
        return _handle_admin_lock(config)
    if args.admin_unlock:
        return _handle_admin_unlock(config)
    if args.security_status:
        return _handle_security_status(config)
    if args.clear_trust:
        return _handle_clear_trust(config.user_dir)

    setup_logging(args.verbose)

    # Handle server mode
    if args.server:
        return _handle_server_mode(config, print_key=args.print_key, config_path=config_path)

    # Handle UI mode (launches floating dictation box)
    if args.ui:
        return _handle_ui_mode(config, inject_method=args.inject_method)
    logger.info("Wispr-Dragon starting...")

    # Initialize components
    dictionary = UserDictionary()
    hotword_mgr = HotwordManager(dictionary, config.correction.max_hotwords)
    post_processor = PostProcessor(
        dictionary,
        fuzzy_threshold=config.correction.fuzzy_match_score,
        auto_apply_threshold=config.correction.auto_apply_threshold,
    )
    injector = TextInjector(method=args.inject_method)
    logger.info("Text injection method: %s", injector.method)

    # Modes, command grammar, handlers and the shared text pipeline.
    mode_mgr, orchestrator = _build_headless_pipeline(config, post_processor, injector)

    # Create and load engine
    engine = create_engine(config)
    logger.info("Loading model: %s", config.engine.model_size)
    engine.load_model(
        config.engine.model_size,
        device=config.engine.device,
        compute_type=config.engine.compute_type,
    )
    logger.info("Model loaded successfully")

    # Create audio source
    audio_source = create_audio_source(config)

    # Set up VAD
    vad = None
    if not args.no_vad:
        from .audio.vad import VoiceActivityDetector
        vad = VoiceActivityDetector(
            sample_rate=config.audio.sample_rate,
            threshold=config.audio.vad_threshold,
            silence_duration_ms=config.audio.silence_duration_ms,
            min_speech_duration_ms=config.audio.min_speech_duration_ms,
        )
        vad.load()
        logger.info("VAD loaded")

    # Signal handling
    running = True

    def signal_handler(sig, frame):
        nonlocal running
        running = False
        logger.info("Shutting down...")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Main loop
    logger.info("Ready. Listening... (Ctrl+C to quit)")
    audio_source.start()

    try:
        while running:
            chunk = audio_source.read(timeout=0.5)
            if chunk is None:
                continue

            if vad is not None:
                speech_segment = vad.process_chunk(chunk)
                if speech_segment is None:
                    continue
                audio_data = speech_segment
            else:
                audio_data = chunk.flatten()

            # Transcribe
            result = engine.transcribe(
                audio_data,
                language=config.engine.language,
                initial_prompt=hotword_mgr.get_initial_prompt(),
                hotwords=hotword_mgr.get_hotwords(),
                beam_size=config.engine.beam_size,
            )

            if not result or not result.text.strip():
                continue

            # Post-process + route through modes/commands via the shared pipeline,
            # then inject (and record for undo) exactly what is typed.
            outcome = orchestrator.handle_transcript(result.text)
            _emit_headless(outcome, injector, mode_mgr)

    finally:
        audio_source.stop()
        logger.info("Wispr-Dragon stopped")


if __name__ == "__main__":
    main()
