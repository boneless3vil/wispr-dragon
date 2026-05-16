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

    def __init__(self, config, user_dir: Path, engine, post_processor=None, text_injector=None):
        """Initialize UI controller.

        Args:
            config: Config object
            user_dir: User config directory (~/.wispr_dragon)
            engine: TranscriptionEngine instance
            post_processor: PostProcessor for text correction (optional)
            text_injector: TextInjector for posting text (optional)
        """
        self.config = config
        self.user_dir = user_dir
        self.engine = engine
        self.post_processor = post_processor
        self.text_injector = text_injector

        self.dictation_box = None
        self.audio_worker = None
        self.transcription_worker = None
        self.audio_thread = None
        self.transcription_thread = None
        self.is_running = False

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
                post_processor=self.post_processor,
                on_transcription=self._on_transcription,
                on_error=self._on_error,
            )

            # Create UI
            self.dictation_box = DictationBox(
                self.config,
                self.user_dir,
                on_text_ready=self._on_text_ready,
            )

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

            # Show UI (blocks until window closes)
            self.dictation_box.show()
            logger.info("Dictation session started")
            return True

        except Exception as e:
            logger.error("Failed to start dictation: %s", e)
            self.stop()
            return False

    def stop(self):
        """Stop dictation session (close UI + stop threads)."""
        self.is_running = False

        if self.dictation_box:
            try:
                self.dictation_box.close()
            except Exception as e:
                logger.warning("Error closing dictation box: %s", e)

        if self.audio_worker:
            self.audio_worker.stop_recording()
            self.audio_worker.cleanup()

        if self.transcription_worker:
            self.transcription_worker.reset()

        # Wait for threads
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=2)

        if self.transcription_thread and self.transcription_thread.is_alive():
            self.transcription_thread.join(timeout=2)

        logger.info("Dictation session stopped")

    def _audio_thread_main(self):
        """Run audio capture in separate thread."""
        try:
            if self.audio_worker.start_recording():
                # Keep thread alive while recording
                while self.is_running:
                    threading.Event().wait(0.1)
        except Exception as e:
            logger.error("Audio thread error: %s", e)
            if self.dictation_box:
                self.dictation_box.status_bar.showMessage(f"Error: {e}")

    def _transcription_thread_main(self):
        """Run transcription in separate thread."""
        try:
            while self.is_running:
                threading.Event().wait(0.5)
        except Exception as e:
            logger.error("Transcription thread error: %s", e)

    def _on_audio_chunk(self, chunk):
        """Callback from AudioWorker when audio chunk is ready."""
        if self.transcription_worker:
            self.transcription_worker.process_audio_chunk(chunk)

    def _on_transcription(self, live: str, final: Optional[str]):
        """Callback from TranscriptionWorker when transcription updates."""
        if self.dictation_box:
            # Update UI from worker thread
            try:
                self.dictation_box.update_transcription(live, final)
            except Exception as e:
                logger.error("Error updating transcription: %s", e)

    def _on_text_ready(self, text: str):
        """Callback from DictationBox when user clicks Post."""
        # Finalize any pending transcription
        if self.transcription_worker:
            final_text = self.transcription_worker.flush_and_finalize()
            if final_text:
                text = final_text

        # Inject text into active window
        if self.text_injector:
            try:
                self.text_injector.inject(text)
                logger.info("Text injected: %d characters", len(text))
            except Exception as e:
                logger.error("Failed to inject text: %s", e)
                if self.dictation_box:
                    self.dictation_box.status_bar.showMessage(f"Error: {e}")

        # Stop recording
        self.stop()

    def _on_error(self, error_msg: str):
        """Callback when audio/transcription worker encounters an error."""
        logger.error("Worker error: %s", error_msg)
        if self.dictation_box:
            try:
                self.dictation_box.status_bar.showMessage(f"Error: {error_msg}")
            except Exception as e:
                logger.warning("Error updating status: %s", e)
