"""Settings dialog for Wispr Dragon configuration."""

import logging
from pathlib import Path
from typing import Optional

from wispr_dragon.config import Config

logger = logging.getLogger(__name__)


class SettingsDialog:
    """PyQt6-based settings dialog for config.yaml editing."""

    def __init__(self, config: Config, parent=None):
        """Initialize settings dialog.

        Args:
            config: Config instance to display/edit
            parent: Parent widget (for modal behavior)
        """
        self.config = config
        self.parent = parent
        self.dialog = None
        self.widgets = {}

    def show(self) -> bool:
        """Show settings dialog and block until closed.

        Returns:
            True if user clicked OK, False if cancelled
        """
        try:
            from PyQt6.QtWidgets import (
                QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
                QComboBox, QPushButton, QFormLayout
            )
        except ImportError:
            logger.warning("PyQt6 not available, skipping settings dialog")
            return False

        self.dialog = QDialog(self.parent)
        self.dialog.setWindowTitle("Wispr Dragon — Settings")
        self.dialog.setGeometry(100, 100, 500, 600)

        layout = QVBoxLayout()

        # Audio settings group
        audio_group = QGroupBox("Audio")
        audio_form = QFormLayout()

        # Sample rate
        sample_rate = QSpinBox()
        sample_rate.setMinimum(8000)
        sample_rate.setMaximum(48000)
        sample_rate.setValue(self.config.audio.sample_rate)
        audio_form.addRow("Sample Rate (Hz):", sample_rate)
        self.widgets["sample_rate"] = sample_rate

        # VAD threshold
        vad_threshold = QDoubleSpinBox()
        vad_threshold.setMinimum(0.0)
        vad_threshold.setMaximum(1.0)
        vad_threshold.setSingleStep(0.05)
        vad_threshold.setValue(self.config.audio.vad_threshold)
        audio_form.addRow("VAD Threshold:", vad_threshold)
        self.widgets["vad_threshold"] = vad_threshold

        audio_group.setLayout(audio_form)
        layout.addWidget(audio_group)

        # Engine settings group
        engine_group = QGroupBox("Engine")
        engine_form = QFormLayout()

        # Model size
        model_combo = QComboBox()
        model_combo.addItems(["tiny.en", "small.en", "base.en", "medium.en", "large-v3"])
        try:
            idx = model_combo.findText(self.config.engine.model_size)
            if idx >= 0:
                model_combo.setCurrentIndex(idx)
        except Exception:
            pass
        engine_form.addRow("Model Size:", model_combo)
        self.widgets["model_size"] = model_combo

        # Device
        device_combo = QComboBox()
        device_combo.addItems(["auto", "cuda", "cpu"])
        try:
            idx = device_combo.findText(self.config.engine.device)
            if idx >= 0:
                device_combo.setCurrentIndex(idx)
        except Exception:
            pass
        engine_form.addRow("Device:", device_combo)
        self.widgets["device"] = device_combo

        engine_group.setLayout(engine_form)
        layout.addWidget(engine_group)

        # Model/device changes only take effect when the engine is reloaded,
        # which happens at startup — make that clear to the user.
        restart_note = QLabel("Note: model and device changes apply after restart.")
        restart_note.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(restart_note)

        # Correction settings group
        correction_group = QGroupBox("Text Correction")
        correction_form = QFormLayout()

        # Fuzzy match threshold
        fuzzy_threshold = QSpinBox()
        fuzzy_threshold.setMinimum(0)
        fuzzy_threshold.setMaximum(100)
        fuzzy_threshold.setValue(int(self.config.correction.fuzzy_match_score))
        correction_form.addRow("Fuzzy Match Score:", fuzzy_threshold)
        self.widgets["fuzzy_match_score"] = fuzzy_threshold

        correction_group.setLayout(correction_form)
        layout.addWidget(correction_group)

        # Button layout
        button_layout = QHBoxLayout()

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self._on_ok)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._on_cancel)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.dialog.setLayout(layout)

        # Show modal dialog
        result = self.dialog.exec()
        return result == QDialog.DialogCode.Accepted

    def _on_ok(self) -> None:
        """Handle OK button — save settings and close."""
        try:
            # Update config from widgets
            self.config.audio.sample_rate = self.widgets["sample_rate"].value()
            self.config.audio.vad_threshold = self.widgets["vad_threshold"].value()
            self.config.engine.model_size = self.widgets["model_size"].currentText()
            self.config.engine.device = self.widgets["device"].currentText()
            self.config.correction.fuzzy_match_score = self.widgets["fuzzy_match_score"].value()

            # Save to config file
            self.config.save()
            logger.info("Settings saved successfully")
            self.dialog.accept()
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

    def _on_cancel(self) -> None:
        """Handle Cancel button — discard changes and close."""
        self.dialog.reject()
