"""UI components for Wispr Dragon.

Nothing is imported eagerly: light modules such as ``ui.mic_state`` (imported by
``wispr_dragon.icons``, which the lean Windows client uses) must not drag in
PyQt6, every dialog and ``gpu_advisor``. ``from wispr_dragon.ui import X`` still
works — the names below resolve on first access (PEP 562).
"""

from importlib import import_module

# Public name -> submodule that defines it.
_EXPORTS = {
    "ConfirmationDialog": "confirm_command",
    "TrustManifest": "confirm_command",
    "CorrectionWindow": "correction_window",
    "DictationBox": "dictation_box",
    "AudioWorker": "audio_worker",
    "TranscriptionWorker": "transcription_worker",
    "UIController": "ui_controller",
    "SystemTray": "system_tray",
    "SettingsDialog": "settings_dialog",
    "MacroEditor": "macro_editor",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value  # cache: later lookups skip __getattr__
    return value
