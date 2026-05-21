"""Macro editor for creating and managing voice commands."""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class MacroEditor:
    """PyQt6-based editor for YAML macro files."""

    def __init__(self, user_dir: Path, parent=None):
        """Initialize macro editor.

        Args:
            user_dir: User config directory (~/.wispr_dragon)
            parent: Parent widget (for modal behavior)
        """
        self.user_dir = user_dir
        self.parent = parent
        self.macros_dir = user_dir / "macros"
        self.macros_dir.mkdir(parents=True, exist_ok=True)
        self.dialog = None
        self.macro_list = None
        self.selected_macro = None

    def show(self) -> bool:
        """Show macro editor dialog.

        Returns:
            True if dialog accepted
        """
        try:
            from PyQt6.QtWidgets import (
                QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                QGroupBox, QLabel, QLineEdit, QComboBox, QTextEdit,
                QPushButton, QFormLayout, QMessageBox
            )
            from PyQt6.QtCore import Qt
        except ImportError:
            logger.warning("PyQt6 not available, skipping macro editor")
            return False

        self.dialog = QDialog(self.parent)
        self.dialog.setWindowTitle("Wispr Dragon — Macro Editor")
        self.dialog.setGeometry(100, 100, 700, 600)

        main_layout = QHBoxLayout()

        # Left side: macro list
        list_layout = QVBoxLayout()
        list_label = QLabel("Macros:")
        list_layout.addWidget(list_label)

        self.macro_list = QListWidget()
        self._load_macro_list()
        self.macro_list.itemClicked.connect(self._on_macro_selected)
        list_layout.addWidget(self.macro_list)

        # Buttons for list
        list_button_layout = QHBoxLayout()
        new_btn = QPushButton("+ New")
        new_btn.clicked.connect(self._on_new_macro)
        list_button_layout.addWidget(new_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete_macro)
        list_button_layout.addWidget(delete_btn)

        list_layout.addLayout(list_button_layout)
        main_layout.addLayout(list_layout, 1)

        # Right side: macro editor
        editor_layout = QVBoxLayout()
        editor_group = QGroupBox("Edit Macro")
        editor_form = QFormLayout()

        # Trigger
        trigger_input = QLineEdit()
        trigger_input.setPlaceholderText("e.g., 'open browser'")
        editor_form.addRow("Trigger:", trigger_input)
        self.trigger_input = trigger_input

        # Action type
        action_combo = QComboBox()
        action_combo.addItems(["launch", "text", "keystroke", "python_script"])
        editor_form.addRow("Action:", action_combo)
        self.action_combo = action_combo

        # Target/Program
        target_input = QLineEdit()
        target_input.setPlaceholderText("e.g., 'firefox' or 'my_script.py'")
        editor_form.addRow("Target:", target_input)
        self.target_input = target_input

        # Content (for text action)
        content_input = QTextEdit()
        content_input.setPlaceholderText("Text to inject or script content")
        content_input.setMaximumHeight(100)
        editor_form.addRow("Content:", content_input)
        self.content_input = content_input

        editor_group.setLayout(editor_form)
        editor_layout.addWidget(editor_group)

        # Save/Cancel buttons
        editor_button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save_macro)
        editor_button_layout.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.dialog.accept)
        editor_button_layout.addWidget(close_btn)

        editor_layout.addLayout(editor_button_layout)
        main_layout.addLayout(editor_layout, 1)

        self.dialog.setLayout(main_layout)
        return self.dialog.exec() == QDialog.DialogCode.Accepted

    def _load_macro_list(self) -> None:
        """Load all YAML macros from macros directory."""
        try:
            macro_files = list(self.macros_dir.glob("*.yaml"))
            for macro_file in macro_files:
                item = QListWidgetItem(macro_file.stem)
                item.setData(256, str(macro_file))  # Store full path
                self.macro_list.addItem(item)
        except Exception as e:
            logger.error("Failed to load macro list: %s", e)

    def _on_macro_selected(self, item) -> None:
        """Load selected macro into editor."""
        try:
            import yaml
            macro_path = Path(item.data(256))
            with open(macro_path) as f:
                macros = yaml.safe_load(f) or []

            if macros and isinstance(macros, list) and len(macros) > 0:
                macro = macros[0]
                self.selected_macro = macro_path
                self.trigger_input.setText(macro.get("trigger", ""))
                self.action_combo.setCurrentText(macro.get("action", "launch"))
                self.target_input.setText(macro.get("program") or macro.get("script") or "")
                self.content_input.setText(macro.get("content") or "")
        except Exception as e:
            logger.error("Failed to load macro: %s", e)

    def _on_new_macro(self) -> None:
        """Create new macro."""
        self.selected_macro = None
        self.trigger_input.clear()
        self.action_combo.setCurrentIndex(0)
        self.target_input.clear()
        self.content_input.clear()

    def _on_delete_macro(self) -> None:
        """Delete selected macro."""
        try:
            item = self.macro_list.currentItem()
            if not item:
                return
            macro_path = Path(item.data(256))
            macro_path.unlink()
            self.macro_list.takeItem(self.macro_list.row(item))
            logger.info("Deleted macro: %s", macro_path.name)
        except Exception as e:
            logger.error("Failed to delete macro: %s", e)

    def _on_save_macro(self) -> None:
        """Save current macro to YAML."""
        try:
            import yaml

            trigger = self.trigger_input.text().strip()
            action = self.action_combo.currentText()
            target = self.target_input.text().strip()
            content = self.content_input.toPlainText().strip()

            if not trigger:
                logger.warning("Trigger is required")
                return

            # Build macro entry
            macro = {
                "trigger": trigger,
                "action": action,
            }

            if action == "launch":
                macro["program"] = target
            elif action == "python_script":
                macro["script"] = target
            elif action == "keystroke":
                macro["keys"] = target
            elif action == "text":
                macro["content"] = content

            # Determine filename
            if self.selected_macro:
                filename = self.selected_macro
            else:
                filename = self.macros_dir / f"{trigger.replace(' ', '_')}.yaml"

            # Write YAML
            with open(filename, "w") as f:
                yaml.dump([macro], f, default_flow_style=False)

            logger.info("Saved macro: %s", filename.name)
            self._load_macro_list()
        except Exception as e:
            logger.error("Failed to save macro: %s", e)
