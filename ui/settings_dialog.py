"""Tela de configurações: provedor de IA, API key e modelo Whisper.

As API keys são salvas no cofre do sistema operacional (keyring) via
ProviderManager — nunca em texto puro, quando o keyring está disponível.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
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
        pack_manager=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.image_manager = image_manager or ImageProviderManager()
        self.settings = settings
        self._pack_manager = pack_manager
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.provider_combo = QComboBox()
        self.model_edit = QLineEdit()
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(
            "URL base (opcional — ex.: http://localhost:11434 para Ollama)"
        )
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
        form.addRow("URL base:", self.base_url_edit)
        form.addRow("API Key:", self.key_edit)
        form.addRow("", key_hint)
        form.addRow("Modelo Whisper:", self.whisper_combo)
        form.addRow("Posição da legenda:", self.position_spin)
        form.addRow("", position_hint)

        image_title = QLabel("Destaques em imagem (B-roll)")
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

        # ------------------------------------------------------------------
        # Pack de assets externo (Fase 7)
        # ------------------------------------------------------------------
        from core.pack_manager import PACK_CATEGORIES

        pack_title = QLabel("Pack de assets (HD externo)")
        pack_title.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(pack_title)

        pack_root_row = QHBoxLayout()
        self.pack_root_edit = QLineEdit()
        self.pack_root_edit.setText(self.settings.pack_root)
        self.pack_root_edit.setPlaceholderText(
            "Pasta raiz do pack (ex.: E:\\Packs CapCut\\CapCut Pack) — "
            "as categorias são detectadas pelos nomes das subpastas"
        )
        pack_root_browse = QPushButton("Procurar…")
        pack_root_browse.clicked.connect(self._browse_pack_root)
        pack_root_row.addWidget(self.pack_root_edit, 1)
        pack_root_row.addWidget(pack_root_browse)
        layout.addLayout(pack_root_row)

        self.pack_table = QTableWidget(len(PACK_CATEGORIES), 2)
        self.pack_table.setHorizontalHeaderLabels(["Categoria", "Pasta (opcional)"])
        self.pack_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.pack_table.setMinimumHeight(220)
        self._pack_row_categories: list[str] = []
        for row, (cat_id, meta) in enumerate(PACK_CATEGORIES.items()):
            label_item = QTableWidgetItem(meta["label"])
            label_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.pack_table.setItem(row, 0, label_item)
            path_item = QTableWidgetItem(
                (self.settings.pack_folders or {}).get(cat_id, "")
            )
            self.pack_table.setItem(row, 1, path_item)
            self._pack_row_categories.append(cat_id)
        layout.addWidget(self.pack_table)

        pack_buttons = QHBoxLayout()
        detect_btn = QPushButton("Detectar pastas pela raiz")
        detect_btn.clicked.connect(self._detect_pack_folders)
        browse_row_btn = QPushButton("Procurar pasta da linha selecionada…")
        browse_row_btn.clicked.connect(self._browse_pack_row)
        rescan_btn = QPushButton("Rescanear pack")
        rescan_btn.clicked.connect(self._rescan_pack)
        pack_buttons.addWidget(detect_btn)
        pack_buttons.addWidget(browse_row_btn)
        pack_buttons.addStretch(1)
        pack_buttons.addWidget(rescan_btn)
        layout.addLayout(pack_buttons)

        self.pack_status = QLabel(
            "Arquivos lidos direto do HD em tempo de execução — nada é "
            "embutido no instalador. Sem o HD, o app usa os assets padrão."
        )
        self.pack_status.setStyleSheet("color: gray; font-size: 11px;")
        self.pack_status.setWordWrap(True)
        layout.addWidget(self.pack_status)

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
                self.base_url_edit.setText(provider.get("base_url", ""))
                self.base_url_edit.setEnabled(provider.get("supports_base_url", False))
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

    # ------------------------------------------------------------------
    # Pack externo (Fase 7)
    # ------------------------------------------------------------------

    def _browse_pack_root(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(
            self, "Escolher a pasta raiz do pack"
        )
        if path:
            self.pack_root_edit.setText(path)
            self._apply_root_and_detect(path)

    def _apply_root_and_detect(self, root: str) -> None:
        """Aplica a raiz e preenche as linhas com as pastas detectadas."""
        temp_settings = type(self.settings)()
        temp_settings.pack_root = root
        from core.pack_manager import PackManager

        manager = PackManager(temp_settings)
        detected = manager.detect_categories_from_root()
        folders = temp_settings.pack_folders or {}
        for row, cat_id in enumerate(self._pack_row_categories):
            if cat_id in folders:
                self.pack_table.item(row, 1).setText(folders[cat_id])
        self.pack_status.setText(
            f"{detected} categoria(s) detectada(s) na raiz informada."
        )

    def _detect_pack_folders(self) -> None:
        self._apply_root_and_detect(self.pack_root_edit.text().strip())

    def _browse_pack_row(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        row = self.pack_table.currentRow()
        if row < 0:
            self.pack_status.setText("Selecione uma categoria na tabela primeiro.")
            return
        path = QFileDialog.getExistingDirectory(
            self,
            f"Pasta da categoria: {self.pack_table.item(row, 0).text()}",
        )
        if path:
            self.pack_table.item(row, 1).setText(path)

    def _rescan_pack(self) -> None:
        """Simula o scan com o que está na tela agora (sem salvar)."""
        from core.pack_manager import PackManager

        temp_settings = type(self.settings)()
        temp_settings.pack_root = self.pack_root_edit.text().strip()
        temp_settings.pack_folders = self._collect_pack_folders()
        manager = PackManager(temp_settings)
        index = manager.scan()
        total = sum(len(v) for v in index.values())
        cats = sum(1 for v in index.values() if v)
        missing = manager.missing_categories()
        status = f"{total} arquivo(s) em {cats} categoria(s)."
        if missing:
            status += f" Ausentes (HD desconectado?): {', '.join(missing)}."
        self.pack_status.setText(status)

    def _collect_pack_folders(self) -> dict:
        folders = {}
        for row, cat_id in enumerate(self._pack_row_categories):
            item = self.pack_table.item(row, 1)
            text = item.text().strip() if item else ""
            if text:
                folders[cat_id] = text
        return folders

    def _save(self) -> None:
        pid = self.provider_combo.currentData()
        try:
            self.manager.set_active(pid)
            self.manager.set_model(pid, self.model_edit.text().strip())
            self.manager.set_base_url(pid, self.base_url_edit.text().strip())
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
        self.settings.pack_root = self.pack_root_edit.text().strip()
        self.settings.pack_folders = self._collect_pack_folders()
        self.settings.save()
        self.accept()
