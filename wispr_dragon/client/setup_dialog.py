"""First-run / settings dialog for the Windows client.

A lightweight modal QDialog to capture the server URL + API key when the
client has no usable config (first run) or when the user wants to change them
later (tray "Settings…"). Writes back into the client's config dict; the
caller persists via ``WisprDragonClient._save_config``.

Imported only on the Qt/tray path, so PyQt6 stays optional for headless runs.
Validation logic lives in :func:`wispr_dragon.client.app.validate_setup` (pure,
unit-tested without a display) — this module is just the view over it.
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from wispr_dragon.client.app import validate_setup

logger = logging.getLogger(__name__)


class SetupDialog(QDialog):
    """Modal dialog for entering server URL + API key.

    Usage::

        dlg = SetupDialog(client.config)
        if dlg.exec():
            client.config = dlg.result_config()
            client._save_config()
    """

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config)  # work on a copy; commit only on accept
        self._result: dict | None = None

        self.setWindowTitle("Wispr Dragon — Setup")
        self.setModal(True)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Connect to your Wispr Dragon server. Run "
            "<code>--print-key</code> on the server to get these values."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.url_input = QLineEdit(self._config.get("server_url", "ws://localhost:8765"))
        self.url_input.setPlaceholderText("ws://192.168.1.10:8765")
        form.addRow("Server URL:", self.url_input)

        self.key_input = QLineEdit(self._config.get("api_key", ""))
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("paste the API key")
        form.addRow("API Key:", self.key_input)
        layout.addLayout(form)

        self.show_key = QCheckBox("Show key")
        self.show_key.toggled.connect(self._on_show_key_toggled)
        layout.addWidget(self.show_key)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Live validation gates the Save button.
        self.url_input.textChanged.connect(self._revalidate)
        self.key_input.textChanged.connect(self._revalidate)
        self._revalidate()

    def result_config(self) -> dict | None:
        """The updated config dict if saved, else None (cancelled)."""
        return self._result

    # --- internals --------------------------------------------------------

    def _save_button(self):
        return self.buttons.button(QDialogButtonBox.StandardButton.Save)

    def _on_show_key_toggled(self, checked: bool) -> None:
        self.key_input.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def _revalidate(self) -> None:
        ok, msg = validate_setup(self.url_input.text(), self.key_input.text())
        self.error_label.setText("" if ok else msg)
        btn = self._save_button()
        if btn is not None:
            btn.setEnabled(ok)

    def _on_save(self) -> None:
        ok, msg = validate_setup(self.url_input.text(), self.key_input.text())
        if not ok:
            self.error_label.setText(msg)
            return
        self._config["server_url"] = self.url_input.text().strip()
        self._config["api_key"] = self.key_input.text().strip()
        self._result = self._config
        logger.info("Setup saved: server_url set, api_key set")
        self.accept()
