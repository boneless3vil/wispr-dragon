"""UI components for Wispr Dragon."""

from .confirm_command import ConfirmationDialog, TrustManifest
from .correction_window import CorrectionWindow
from .dictation_box import DictationBox
from .audio_worker import AudioWorker
from .transcription_worker import TranscriptionWorker
from .ui_controller import UIController
from .system_tray import SystemTray
from .settings_dialog import SettingsDialog
from .macro_editor import MacroEditor

__all__ = [
    "ConfirmationDialog",
    "TrustManifest",
    "CorrectionWindow",
    "DictationBox",
    "AudioWorker",
    "TranscriptionWorker",
    "UIController",
    "SystemTray",
    "SettingsDialog",
    "MacroEditor",
]
