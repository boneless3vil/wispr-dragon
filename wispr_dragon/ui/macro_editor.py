"""Command & Vocabulary browser (Dragon-16-style).

Single dialog with two tabs:

- **Commands**: edit YAML macros under ``~/.wispr_dragon/macros/*.yaml``
  (launch / text / keystroke / python_script actions). This is the original
  ``MacroEditor`` form, unchanged in behavior. Saving a macro never trusts or
  executes it -- trust stays at execution time via the ConfirmationDialog /
  trust_manifest flow.
- **Vocabulary**: custom words and corrections backed by
  :class:`~wispr_dragon.correction.dictionary.UserDictionary`.

The class is still named ``MacroEditor`` for backward compatibility; the
Commands tab IS the macro editor. The Qt-free logic (macro dict building,
vocabulary mutation) lives in module-level helpers so it can be unit-tested
headlessly.
"""

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _check_pyqt6() -> bool:
    """Return True if PyQt6 is importable (mirrors correction_window)."""
    try:
        from PyQt6.QtWidgets import QApplication  # noqa: F401
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------- #
# Qt-free helpers (unit-testable)
# --------------------------------------------------------------------------- #

def build_macro_entry(
    trigger: str,
    action: str,
    target: str = "",
    content: str = "",
) -> dict[str, Any]:
    """Build a single macro dict from form fields.

    Pure function -- no Qt, no disk. Mirrors the action-specific field layout
    used by ``MacroRunner``. Does not validate trust; saving never trusts.

    Raises:
        ValueError: if trigger is empty.
    """
    trigger = trigger.strip()
    if not trigger:
        raise ValueError("Trigger is required")

    macro: dict[str, Any] = {"trigger": trigger, "action": action}
    target = target.strip()
    if action == "launch":
        macro["program"] = target
    elif action == "python_script":
        macro["script"] = target
    elif action == "keystroke":
        macro["keys"] = target
    elif action == "text":
        macro["content"] = content.strip()
    return macro


def macro_filename_for(trigger: str) -> str:
    """Derive a YAML filename stem+ext for a new macro trigger."""
    return f"{trigger.strip().replace(' ', '_')}.yaml"


def add_custom_word(dictionary, word: str) -> bool:
    """Add a custom word to the dictionary. Returns True if added.

    Qt-free. Idempotent: returns False if blank or already present.
    """
    word = (word or "").strip()
    if not word:
        return False
    if word in dictionary.custom_words:
        return False
    dictionary.add_custom_word(word)
    return True


def remove_custom_word(dictionary, word: str) -> bool:
    """Remove a custom word from the dictionary. Returns True if removed."""
    return dictionary.remove_custom_word((word or "").strip())


def add_correction(dictionary, wrong: str, correct: str) -> bool:
    """Add a wrong->right correction. Returns True if recorded."""
    wrong = (wrong or "").strip()
    correct = (correct or "").strip()
    if not wrong or not correct:
        return False
    dictionary.add_correction(wrong, correct)
    return True


def remove_correction(dictionary, wrong: str) -> bool:
    """Remove a correction by its wrong-text key. Returns True if removed."""
    return dictionary.remove_correction((wrong or "").strip())


# --------------------------------------------------------------------------- #
# Dialog
# --------------------------------------------------------------------------- #

class MacroEditor:
    """PyQt6 Command & Vocabulary browser.

    Backward-compatible name and constructor: ``MacroEditor(user_dir, parent)``
    still works. Pass an optional ``dictionary`` (a ``UserDictionary``) to
    populate the Vocabulary tab; if omitted, one is constructed lazily from the
    default path when the dialog is shown.
    """

    def __init__(self, user_dir: Path, parent=None, dictionary=None):
        """Initialize the editor.

        Args:
            user_dir: User config directory (~/.wispr_dragon)
            parent: Parent widget (for modal behavior)
            dictionary: Optional UserDictionary for the Vocabulary tab.
        """
        self.user_dir = user_dir
        self.parent = parent
        self.macros_dir = user_dir / "macros"
        self.macros_dir.mkdir(parents=True, exist_ok=True)
        self.dictionary = dictionary
        self.dialog = None
        self.macro_list = None
        self.selected_macro = None
        # Vocabulary widgets
        self.words_list = None
        self.corrections_list = None

    def _ensure_dictionary(self):
        """Lazily build a UserDictionary if none was injected."""
        if self.dictionary is None:
            from ..correction.dictionary import UserDictionary
            self.dictionary = UserDictionary()
        return self.dictionary

    def show(self) -> bool:
        """Show the Command & Vocabulary browser dialog.

        Returns:
            True if dialog accepted.
        """
        if not _check_pyqt6():
            logger.warning("PyQt6 not available, skipping command/vocabulary browser")
            return False

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTabWidget

        self.dialog = QDialog(self.parent)
        self.dialog.setWindowTitle("Wispr Dragon — Commands & Vocabulary")
        self.dialog.setGeometry(100, 100, 720, 600)

        layout = QVBoxLayout()
        tabs = QTabWidget()
        tabs.setObjectName("commandVocabTabs")
        tabs.addTab(self._build_commands_tab(), "Commands")
        tabs.addTab(self._build_vocabulary_tab(), "Vocabulary")
        layout.addWidget(tabs)
        self.dialog.setLayout(layout)
        self.dialog.setStyleSheet(self._stylesheet())
        return self.dialog.exec() == QDialog.DialogCode.Accepted

    @staticmethod
    def _stylesheet() -> str:
        """Sage-green accent, object-name-scoped (matches existing UI)."""
        return (
            "QTabWidget#commandVocabTabs::pane { border: 1px solid #8a9a5b; }"
            "QTabBar::tab:selected { background: #8a9a5b; color: white; }"
            "QPushButton#vocabAccentBtn { background: #8a9a5b; color: white; }"
        )

    # ----------------------------- Commands tab ---------------------------- #

    def _build_commands_tab(self):
        """Build the original macro-editing form as a tab widget."""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QGroupBox,
            QLabel, QLineEdit, QComboBox, QTextEdit, QPushButton, QFormLayout,
        )

        tab = QWidget()
        main_layout = QHBoxLayout()

        # Left side: macro list
        list_layout = QVBoxLayout()
        list_layout.addWidget(QLabel("Commands:"))

        self.macro_list = QListWidget()
        self._load_macro_list()
        self.macro_list.itemClicked.connect(self._on_macro_selected)
        list_layout.addWidget(self.macro_list)

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
        editor_group = QGroupBox("Edit Command")
        editor_form = QFormLayout()

        self.trigger_input = QLineEdit()
        self.trigger_input.setPlaceholderText("e.g., 'open browser'")
        editor_form.addRow("Trigger:", self.trigger_input)

        self.action_combo = QComboBox()
        self.action_combo.addItems(["launch", "text", "keystroke", "python_script"])
        editor_form.addRow("Action:", self.action_combo)

        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("e.g., 'firefox' or 'my_script.py'")
        editor_form.addRow("Target:", self.target_input)

        self.content_input = QTextEdit()
        self.content_input.setPlaceholderText("Text to inject or script content")
        self.content_input.setMaximumHeight(100)
        editor_form.addRow("Content:", self.content_input)

        editor_group.setLayout(editor_form)
        editor_layout.addWidget(editor_group)

        editor_button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save_macro)
        editor_button_layout.addWidget(save_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.dialog.accept)
        editor_button_layout.addWidget(close_btn)
        editor_layout.addLayout(editor_button_layout)
        main_layout.addLayout(editor_layout, 1)

        tab.setLayout(main_layout)
        return tab

    def _load_macro_list(self) -> None:
        """Load all YAML macros from macros directory."""
        try:
            from PyQt6.QtWidgets import QListWidgetItem
            for macro_file in self.macros_dir.glob("*.yaml"):
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
        """Save current macro to YAML. Saving never trusts/executes the macro."""
        try:
            import yaml

            try:
                macro = build_macro_entry(
                    self.trigger_input.text(),
                    self.action_combo.currentText(),
                    self.target_input.text(),
                    self.content_input.toPlainText(),
                )
            except ValueError as e:
                logger.warning("%s", e)
                return

            if self.selected_macro:
                filename = self.selected_macro
            else:
                filename = self.macros_dir / macro_filename_for(macro["trigger"])

            with open(filename, "w") as f:
                yaml.dump([macro], f, default_flow_style=False)

            logger.info("Saved macro: %s", filename.name)
            self.macro_list.clear()
            self._load_macro_list()
        except Exception as e:
            logger.error("Failed to save macro: %s", e)

    # ---------------------------- Vocabulary tab --------------------------- #

    def _build_vocabulary_tab(self):
        """Build the custom-words + corrections tab backed by UserDictionary."""
        from PyQt6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
            QLineEdit, QListWidget, QPushButton,
        )

        self._ensure_dictionary()
        tab = QWidget()
        layout = QHBoxLayout()

        # Custom words column
        words_group = QGroupBox("Custom Words")
        words_layout = QVBoxLayout()
        self.words_list = QListWidget()
        words_layout.addWidget(self.words_list)

        add_word_row = QHBoxLayout()
        self.word_input = QLineEdit()
        self.word_input.setPlaceholderText("New word")
        add_word_row.addWidget(self.word_input)
        add_word_btn = QPushButton("Add")
        add_word_btn.setObjectName("vocabAccentBtn")
        add_word_btn.clicked.connect(self._on_add_word)
        add_word_row.addWidget(add_word_btn)
        words_layout.addLayout(add_word_row)

        del_word_btn = QPushButton("Remove Selected")
        del_word_btn.clicked.connect(self._on_remove_word)
        words_layout.addWidget(del_word_btn)
        words_group.setLayout(words_layout)
        layout.addWidget(words_group, 1)

        # Corrections column
        corr_group = QGroupBox("Corrections (wrong → right)")
        corr_layout = QVBoxLayout()
        self.corrections_list = QListWidget()
        corr_layout.addWidget(self.corrections_list)

        add_corr_row = QHBoxLayout()
        self.wrong_input = QLineEdit()
        self.wrong_input.setPlaceholderText("Heard as…")
        add_corr_row.addWidget(self.wrong_input)
        self.correct_input = QLineEdit()
        self.correct_input.setPlaceholderText("Should be…")
        add_corr_row.addWidget(self.correct_input)
        add_corr_btn = QPushButton("Add")
        add_corr_btn.setObjectName("vocabAccentBtn")
        add_corr_btn.clicked.connect(self._on_add_correction)
        add_corr_row.addWidget(add_corr_btn)
        corr_layout.addLayout(add_corr_row)

        del_corr_btn = QPushButton("Remove Selected")
        del_corr_btn.clicked.connect(self._on_remove_correction)
        corr_layout.addWidget(del_corr_btn)
        corr_group.setLayout(corr_layout)
        layout.addWidget(corr_group, 1)

        tab.setLayout(layout)
        self._refresh_vocabulary()
        return tab

    def _refresh_vocabulary(self) -> None:
        """Repopulate both vocabulary lists from the dictionary."""
        try:
            self.words_list.clear()
            for word in self.dictionary.custom_words:
                self.words_list.addItem(word)

            self.corrections_list.clear()
            for wrong, entry in self.dictionary.corrections.items():
                correct = entry.get("correct", "")
                self.corrections_list.addItem(f"{wrong} → {correct}")
        except Exception as e:
            logger.error("Failed to refresh vocabulary: %s", e)

    def _on_add_word(self) -> None:
        if add_custom_word(self.dictionary, self.word_input.text()):
            self.word_input.clear()
            self._refresh_vocabulary()

    def _on_remove_word(self) -> None:
        item = self.words_list.currentItem()
        if item and remove_custom_word(self.dictionary, item.text()):
            self._refresh_vocabulary()

    def _on_add_correction(self) -> None:
        if add_correction(self.dictionary, self.wrong_input.text(), self.correct_input.text()):
            self.wrong_input.clear()
            self.correct_input.clear()
            self._refresh_vocabulary()

    def _on_remove_correction(self) -> None:
        item = self.corrections_list.currentItem()
        if not item:
            return
        # Stored display form is "wrong → right"; recover the key.
        wrong = item.text().split(" → ", 1)[0]
        if remove_correction(self.dictionary, wrong):
            self._refresh_vocabulary()
