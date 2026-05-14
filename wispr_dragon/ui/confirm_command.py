"""VS Code-style confirmation dialog for commands detected during dictation."""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TrustManifest:
    """Manage trusted programs and scripts to skip confirmation."""

    def __init__(self, user_dir: Path):
        """Initialize trust manifest.

        Args:
            user_dir: User config directory (~/.wispr_dragon)
        """
        self.manifest_file = user_dir / "trusted.json"
        self._cache = None

    def is_trusted(self, program_or_script: str) -> bool:
        """Check if a program/script is in the trust list.

        Args:
            program_or_script: Program name (firefox) or script name (my_script.py)

        Returns:
            True if in trust list
        """
        data = self._load()
        programs = data.get("programs", [])
        scripts = data.get("scripts", [])
        return program_or_script in programs or program_or_script in scripts

    def add_trust(self, program_or_script: str, is_script: bool = False) -> bool:
        """Add program/script to trust list.

        Args:
            program_or_script: Program or script name
            is_script: True if it's a Python script, False if program

        Returns:
            True on success
        """
        try:
            data = self._load()
            key = "scripts" if is_script else "programs"
            if program_or_script not in data[key]:
                data[key].append(program_or_script)
                self._save(data)
            logger.info("Added to trust list: %s", program_or_script)
            return True
        except Exception as e:
            logger.error("Failed to add trust: %s", e)
            return False

    def remove_trust(self, program_or_script: str) -> bool:
        """Remove from trust list.

        Args:
            program_or_script: Program or script name

        Returns:
            True on success
        """
        try:
            data = self._load()
            for key in ("programs", "scripts"):
                if program_or_script in data[key]:
                    data[key].remove(program_or_script)
            self._save(data)
            logger.info("Removed from trust list: %s", program_or_script)
            return True
        except Exception as e:
            logger.error("Failed to remove trust: %s", e)
            return False

    def clear_all(self) -> bool:
        """Clear all trusted entries."""
        try:
            self._save({"programs": [], "scripts": []})
            self._cache = None
            logger.info("Trust list cleared")
            return True
        except Exception as e:
            logger.error("Failed to clear trust: %s", e)
            return False

    def _load(self) -> dict:
        """Load manifest from disk."""
        if self._cache is not None:
            return self._cache

        if not self.manifest_file.exists():
            self._cache = {"programs": [], "scripts": []}
            return self._cache

        try:
            with open(self.manifest_file) as f:
                self._cache = json.load(f)
            return self._cache
        except Exception as e:
            logger.warning("Failed to load trust manifest: %s", e)
            self._cache = {"programs": [], "scripts": []}
            return self._cache

    def _save(self, data: dict) -> None:
        """Save manifest to disk."""
        try:
            self.manifest_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.manifest_file, "w") as f:
                json.dump(data, f, indent=2)
            self.manifest_file.chmod(0o600)
            self._cache = data
        except Exception as e:
            logger.error("Failed to save trust manifest: %s", e)


class ConfirmationDialog:
    """PyQt6-based VS Code-style trust dialog.

    Shows when a command is detected while user is in dictation mode.
    """

    def __init__(self, user_dir: Path, parent=None):
        """Initialize confirmation dialog.

        Args:
            user_dir: User config directory
            parent: Parent widget (for modal behavior)
        """
        self.user_dir = user_dir
        self.parent = parent
        self.trust_manifest = TrustManifest(user_dir)

    def show_and_ask(
        self,
        command_text: str,
        trigger: str,
        action: str,
        target: Optional[str] = None,
    ) -> Optional[str]:
        """Show confirmation dialog and return user's choice.

        Args:
            command_text: What was heard (e.g., "open firefox")
            trigger: Macro trigger that matched (e.g., "open {app}")
            action: Action type (launch, python_script, etc)
            target: Program/script name being triggered

        Returns:
            One of: "yes", "no", "trust", or None (dialog cancelled)
        """
        try:
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
            from PyQt6.QtCore import Qt
        except ImportError:
            logger.warning("PyQt6 not available, falling back to terminal prompt")
            return self._terminal_prompt(command_text, trigger, action, target)

        dialog = QDialog(self.parent)
        dialog.setWindowTitle("Wispr Dragon — Command Detected")
        dialog.setGeometry(100, 100, 500, 200)

        layout = QVBoxLayout()

        # Title
        title = QLabel("Command Detected During Dictation")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Info
        info_text = f"Voice recognized:\n  "{command_text}"\n\nAction:\n  {action}"
        if target:
            info_text += f"\n  Target: {target}"

        info = QLabel(info_text)
        info.setStyleSheet("font-family: monospace; margin: 10px 0;")
        layout.addWidget(info)

        # Buttons
        button_layout = QHBoxLayout()

        yes_btn = QPushButton("Yes, run it")
        yes_btn.clicked.connect(lambda: (dialog.done(1)))
        button_layout.addWidget(yes_btn)

        no_btn = QPushButton("No, type it")
        no_btn.clicked.connect(lambda: (dialog.done(2)))
        button_layout.addWidget(no_btn)

        trust_btn = QPushButton("Trust always")
        trust_btn.clicked.connect(lambda: (dialog.done(3)))
        button_layout.addWidget(trust_btn)

        layout.addLayout(button_layout)
        dialog.setLayout(layout)

        result = dialog.exec()

        if result == 1:
            return "yes"
        elif result == 2:
            return "no"
        elif result == 3:
            return "trust"
        else:
            return None

    def _terminal_prompt(
        self,
        command_text: str,
        trigger: str,
        action: str,
        target: Optional[str] = None,
    ) -> Optional[str]:
        """Fallback terminal-based confirmation prompt."""
        print("\n" + "=" * 50)
        print("Wispr Dragon — Command Detected")
        print("=" * 50)
        print(f"\nVoice: "{command_text}"")
        print(f"Action: {action}")
        if target:
            print(f"Target: {target}")

        while True:
            choice = input("\n[y]es / [n]o / [t]rust always: ").lower().strip()
            if choice in ("y", "yes"):
                return "yes"
            elif choice in ("n", "no"):
                return "no"
            elif choice in ("t", "trust"):
                return "trust"
            else:
                print("Please enter y, n, or t")
