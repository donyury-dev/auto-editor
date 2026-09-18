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
    QSpinBox,
    QVBoxLayout,
)

from ai.provider_manager import ProviderManager
from config.settings import Settings
from images.manager import ImageProviderManager

logger = logging.getLogger(__name__)

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]


class SettingsDialog(QDialog):
    def __init__(
        self,
        manager: ProviderManager,
        settings: Settings,
        image_manager: ImageProviderManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.image_manager = image_manager or ImageProviderManager()
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

        self.position_spin = QSpinBox()
        self.position_spin.setRange(5, 90)
        self.position_spin.setSuffix("%")
        self.position_spin.setValue(self.settings.caption_vertical_position)
        position_hint = QLabel(
            "Altura da legenda a partir da base da tela "
            "(maior = mais para cima)."
        )
        position_hint.setStyleSheet("color: gray; font-size: 11px;")

        form.addRow("Provedor de IA:", self.provider_combo)
        form.addRow("Modelo:", self.model_edit)
        form.addRow("API Key:", self.key_edit)
        form.addRow("", key_hint)
        form.addRow("Modelo Whisper:", self.whisper_combo)
        form.addRow("Posição da legenda:", self.position_spin)
        form.addRow("", position_hint)

        image_title = QLabel("Ilustrações (B-roll)")
        image_title.setStyleSheet("font-weight: bold; margin-top: 8px;")
        form.addRow(image_title)

        self.image_provider_combo = QComboBox()
        self.image_model_edit = QLineEdit()
        self.image_key_edit = QLineEdit()
        self.image_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        image_key_hint = QLabel(
            "A key é salva no cofre do sistema. O provedor local não exige key."
        )
        image_key_hint.setStyleSheet("color: gray; font-size: 11px;")
        image_model_hint = QLabel(
            "Para Stable Diffusion, informe a URL base da API; nos demais, o modelo."
        )
        image_model_hint.setStyleSheet("color: gray; font-size: 11px;")

        form.addRow("Fonte das ilustrações:", self.image_provider_combo)
        form.addRow("Modelo / URL base:", self.image_model_edit)
        form.addRow("API Key da imagem:", self.image_key_edit)
        form.addRow("", image_model_hint)
        form.addRow("", image_key_hint)

        music_title = QLabel("Música e efeitos")
        music_title.setStyleSheet("font-weight: bold; margin-top: 8px;")
        form.addRow(music_title)

        self.music_dir_edit = QLineEdit()
        self.music_dir_edit.setText(self.settings.music_dir)
        self.music_dir_edit.setPlaceholderText(
            "Pasta extra de trilhas (MP3/WAV/M4A/OGG), além de assets/music/"
        )
        music_browse = QPushButton("Procurar…")
        music_browse.clicked.connect(self._browse_music_dir)
        music_row = QHBoxLayout()
        music_row.addWidget(self.music_dir_edit, 1)
        music_row.addWidget(music_browse)
        form.addRow("Pasta de músicas:", music_row)
        music_hint = QLabel(
            "Coloque trilhas livres de direitos na pasta. Um music.json "
            "opcional descreve o clima de cada arquivo. Sem trilhas, o vídeo "
            "sai sem música (os efeitos sonoros continuam)."
        )
        music_hint.setStyleSheet("color: gray; font-size: 11px;")
        music_hint.setWordWrap(True)
        form.addRow("", music_hint)
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

        self._image_providers = self.image_manager.describe_providers()
        for provider in self._image_providers:
            label = provider["label"]
            if provider["requires_api_key"] and not provider["has_key"]:
                label += "  (sem API key)"
            self.image_provider_combo.addItem(label, provider["id"])
        image_index = self.image_provider_combo.findData(
            self.settings.illustration_provider
        )
        if image_index >= 0:
            self.image_provider_combo.setCurrentIndex(image_index)
        self._sync_image_model()
        self.image_provider_combo.currentIndexChanged.connect(
            self._sync_image_model
        )

    def _sync_model(self) -> None:
        pid = self.provider_combo.currentData()
        for provider in self._providers:
            if provider["id"] == pid:
                self.model_edit.setText(provider["model"] or "")
                break

    def _sync_image_model(self) -> None:
        pid = self.image_provider_combo.currentData()
        for provider in self._image_providers:
            if provider["id"] == pid:
                self.image_model_edit.setText(provider["model"] or "")
                break

    def _browse_music_dir(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(
            self, "Escolher pasta de músicas"
        )
        if path:
            self.music_dir_edit.setText(path)

    def _save(self) -> None:
        pid = self.provider_combo.currentData()
        try:
            self.manager.set_active(pid)
            self.manager.set_model(pid, self.model_edit.text().strip())
            key = self.key_edit.text().strip()
            if key:
                self.manager.set_api_key(pid, key)

            image_pid = self.image_provider_combo.currentData()
            self.image_manager.set_model(
                image_pid, self.image_model_edit.text().strip()
            )
            image_key = self.image_key_edit.text().strip()
            if image_key:
                self.image_manager.set_api_key(image_pid, image_key)
        except Exception as exc:
            logger.exception("Falha ao salvar configurações de IA")
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "Erro", f"Falha ao salvar:\n{exc}")
            return
        self.settings.whisper_model = self.whisper_combo.currentText()
        self.settings.caption_vertical_position = self.position_spin.value()
        self.settings.illustration_provider = self.image_provider_combo.currentData()
        self.settings.music_dir = self.music_dir_edit.text().strip()
        self.settings.save()
        self.accept()
