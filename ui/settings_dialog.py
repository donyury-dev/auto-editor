"""Tela de configurações: provedor de IA, API key e modelo Whisper.

As API keys são salvas no cofre do sistema operacional (keyring) via
ProviderManager — nunca em texto puro, quando o keyring está disponível.
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ai.provider_manager import ProviderManager
from config.settings import Settings

logger = logging.getLogger(__name__)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]


class SettingsDialog(QDialog):
    def __init__(
        self,
        manager: ProviderManager,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.settings = settings
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.provider_combo = QComboBox()
        self.model_edit = QLineEdit()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_hint = QLabel(
            "A key é salva no cofre do sistema (keyring). "
            "Deixe em branco para manter a key atual."
        )
        key_hint.setStyleSheet("color: gray; font-size: 11px;")

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(WHISPER_MODELS)
        if self.settings.whisper_model in WHISPER_MODELS:
            self.whisper_combo.setCurrentText(self.settings.whisper_model)

        form.addRow("Provedor de IA:", self.provider_combo)
        form.addRow("Modelo:", self.model_edit)
        form.addRow("API Key:", self.key_edit)
        form.addRow("", key_hint)
        form.addRow("Modelo Whisper:", self.whisper_combo)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Cancelar")
        save_btn = QPushButton("Salvar")
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._save)

        self._providers = self.manager.describe_providers()
        for provider in self._providers:
            label = provider["label"]
            if provider["requires_api_key"] and not provider["has_key"]:
                label += "  (sem API key)"
            self.provider_combo.addItem(label, provider["id"])

        index = self.provider_combo.findData(self.manager.active_id())
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)
        self._sync_model()
        self.provider_combo.currentIndexChanged.connect(self._sync_model)

    def _sync_model(self) -> None:
        pid = self.provider_combo.currentData()
        for provider in self._providers:
            if provider["id"] == pid:
                self.model_edit.setText(provider["model"] or "")
                break

    def _save(self) -> None:
        pid = self.provider_combo.currentData()
        try:
            self.manager.set_active(pid)
            self.manager.set_model(pid, self.model_edit.text().strip())
            key = self.key_edit.text().strip()
            if key:
                self.manager.set_api_key(pid, key)
        except Exception as exc:
            logger.exception("Falha ao salvar configurações de IA")
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "Erro", f"Falha ao salvar:\n{exc}")
            return
        self.settings.whisper_model = self.whisper_combo.currentText()
        self.settings.save()
        self.accept()
