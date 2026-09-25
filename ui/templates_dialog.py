"""Diálogo de seleção e gerenciamento de templates de estilo.

Permite escolher um template built-in ou customizado, editar seus
parâmetros, salvar como novo preset e ver um preview estático.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.settings import Settings
from core.template_preview import generate_template_preview
from core.templates import Template, TemplateManager, apply_template

logger = logging.getLogger(__name__)


class TemplatesDialog(QDialog):
    """Diálogo modal para escolher/editar/salvar templates."""

    def __init__(
        self,
        manager: TemplateManager,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.settings = settings
        self.selected_template: Template | None = None
        self.setWindowTitle("Templates de estilo")
        self.setMinimumSize(900, 700)
        self._build_ui()
        self._populate_combo()
        self._load_template(self.manager.list_templates()[0].id)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)

        # -- coluna esquerda: lista e preview --
        left = QVBoxLayout()

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Template:"))
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        top_row.addWidget(self.combo, 1)
        self.save_btn = QPushButton("Salvar como novo…")
        self.save_btn.clicked.connect(self._save_as_new)
        top_row.addWidget(self.save_btn)
        self.delete_btn = QPushButton("Excluir customizado")
        self.delete_btn.clicked.connect(self._delete_custom)
        top_row.addWidget(self.delete_btn)
        left.addLayout(top_row)

        self.desc_label = QLabel()
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #666;")
        left.addWidget(self.desc_label)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(360, 640)
        self.preview_label.setStyleSheet("background: #222;")
        left.addWidget(self.preview_label, 1)

        self.apply_btn = QPushButton("Aplicar template selecionado")
        self.apply_btn.setStyleSheet("font-size: 14px; padding: 8px;")
        self.apply_btn.clicked.connect(self._apply_and_close)
        left.addWidget(self.apply_btn)

        layout.addLayout(left, 1)

        # -- coluna direita: editor de parâmetros --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        right_widget = QWidget()
        right = QFormLayout(right_widget)

        # Legendas
        leg_group = QGroupBox("Legendas")
        leg_form = QFormLayout(leg_group)
        self.font_edit = QLineEdit()
        self.primary_color = QLineEdit()
        self.highlight_color = QLineEdit()
        self.outline_spin = QSpinBox()
        self.outline_spin.setRange(0, 12)
        self.shadow_spin = QSpinBox()
        self.shadow_spin.setRange(0, 8)
        self.uppercase_check = QLabel("sim")  # simplificado
        self.active_scale = QSpinBox()
        self.active_scale.setRange(100, 200)
        self.position_spin = QSpinBox()
        self.position_spin.setRange(5, 90)
        self.position_spin.setSuffix("%")
        self.max_words = QSpinBox()
        self.max_words.setRange(1, 12)
        self.max_duration = QDoubleSpinBox()
        self.max_duration.setRange(0.5, 6.0)
        self.max_duration.setSingleStep(0.1)
        self.max_duration.setDecimals(1)
        leg_form.addRow("Fonte:", self.font_edit)
        leg_form.addRow("Cor principal:", self.primary_color)
        leg_form.addRow("Cor destaque:", self.highlight_color)
        leg_form.addRow("Contorno:", self.outline_spin)
        leg_form.addRow("Sombra:", self.shadow_spin)
        leg_form.addRow("Caixa alta:", self.uppercase_check)
        leg_form.addRow("Zoom ativo (%):", self.active_scale)
        leg_form.addRow("Posição vertical:", self.position_spin)
        leg_form.addRow("Máx. palavras:", self.max_words)
        leg_form.addRow("Máx. duração (s):", self.max_duration)
        right.addRow(leg_group)

        # Ritmo
        rhythm_group = QGroupBox("Ritmo de edição")
        rhythm_form = QFormLayout(rhythm_group)
        self.transition_combo = QComboBox()
        self.transition_combo.addItems(
            ["corte", "fade", "slideleft", "slideup", "dissolve"]
        )
        self.transition_dur = QDoubleSpinBox()
        self.transition_dur.setRange(0.0, 1.0)
        self.transition_dur.setSingleStep(0.05)
        self.transition_dur.setDecimals(2)
        self.silence_gap = QDoubleSpinBox()
        self.silence_gap.setRange(0.1, 3.0)
        self.silence_gap.setSingleStep(0.1)
        self.silence_gap.setDecimals(1)
        self.zoom_intensity = QDoubleSpinBox()
        self.zoom_intensity.setRange(0.0, 0.5)
        self.zoom_intensity.setSingleStep(0.01)
        self.zoom_intensity.setDecimals(2)
        self.zoom_spread = QDoubleSpinBox()
        self.zoom_spread.setRange(1.0, 15.0)
        self.zoom_spread.setSingleStep(0.5)
        self.zoom_spread.setDecimals(1)
        self.max_zooms = QSpinBox()
        self.max_zooms.setRange(0, 12)
        rhythm_form.addRow("Transição:", self.transition_combo)
        rhythm_form.addRow("Duração transição (s):", self.transition_dur)
        rhythm_form.addRow("Gap mínimo p/ corte (s):", self.silence_gap)
        rhythm_form.addRow("Intensidade do zoom:", self.zoom_intensity)
        rhythm_form.addRow("Espaçamento mín. zoom (s):", self.zoom_spread)
        rhythm_form.addRow("Máx. zooms:", self.max_zooms)
        right.addRow(rhythm_group)

        # Destaques / áudio
        extra_group = QGroupBox("Destaques e áudio")
        extra_form = QFormLayout(extra_group)
        self.illus_density = QDoubleSpinBox()
        self.illus_density.setRange(2.0, 30.0)
        self.illus_density.setSingleStep(1.0)
        self.illus_density.setDecimals(1)
        self.music_mood = QLineEdit()
        extra_form.addRow("Densidade de destaques (s):", self.illus_density)
        extra_form.addRow("Clima musical:", self.music_mood)
        right.addRow(extra_group)

        # Conectar atualização do preview apenas em widgets editáveis
        self.font_edit.textChanged.connect(self._update_preview)
        self.primary_color.textChanged.connect(self._update_preview)
        self.highlight_color.textChanged.connect(self._update_preview)
        for spin in (
            self.outline_spin,
            self.shadow_spin,
            self.active_scale,
            self.position_spin,
            self.max_words,
            self.max_zooms,
        ):
            spin.valueChanged.connect(self._update_preview)
        for dspin in (
            self.max_duration,
            self.transition_dur,
            self.silence_gap,
            self.zoom_intensity,
            self.zoom_spread,
            self.illus_density,
        ):
            dspin.valueChanged.connect(self._update_preview)
        self.transition_combo.currentIndexChanged.connect(self._update_preview)

        self.preview_now_btn = QPushButton("Atualizar preview")
        self.preview_now_btn.clicked.connect(self._update_preview)
        right.addRow(self.preview_now_btn)

        scroll.setWidget(right_widget)
        layout.addWidget(scroll, 1)

        # Botões padrão
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        left.addWidget(self.buttons)

    def _populate_combo(self) -> None:
        self.combo.clear()
        for t in self.manager.list_templates():
            label = t.name
            if self.manager.get(t.id) and t.id not in {bt.id for bt in self.manager._built_in.values()}:
                label += " (customizado)"
            self.combo.addItem(label, t.id)

    def _on_combo_changed(self) -> None:
        tid = self.combo.currentData()
        if tid:
            self._load_template(tid)

    def _load_template(self, template_id: str) -> None:
        t = self.manager.get(template_id)
        if t is None:
            return
        self.selected_template = t
        self.desc_label.setText(t.description)

        self.font_edit.setText(t.font_name)
        self.primary_color.setText(t.primary_color)
        self.highlight_color.setText(t.highlight_color)
        self.outline_spin.setValue(t.outline)
        self.shadow_spin.setValue(t.shadow)
        self.uppercase_check.setText("sim" if t.uppercase else "não")
        self.active_scale.setValue(t.active_scale)
        self.position_spin.setValue(t.caption_vertical_position)
        self.max_words.setValue(t.max_words_per_chunk)
        self.max_duration.setValue(t.max_chunk_duration)
        self.transition_combo.setCurrentText(t.transition_type)
        self.transition_dur.setValue(t.transition_duration)
        self.silence_gap.setValue(t.silence_gap_s)
        self.zoom_intensity.setValue(t.zoom_intensity)
        self.zoom_spread.setValue(t.zoom_spread_s)
        self.max_zooms.setValue(t.max_zooms)
        self.illus_density.setValue(t.illustration_density_s)
        self.music_mood.setText(t.music_mood)

        self.delete_btn.setEnabled(template_id in self.manager._custom)
        self._update_preview()

    def _template_from_editor(self, tid: str, name: str, description: str) -> Template:
        """Monta um Template a partir dos valores atuais do editor."""
        return Template(
            id=tid,
            name=name,
            description=description,
            font_name=self.font_edit.text().strip() or "Anton",
            primary_color=self.primary_color.text().strip() or "#FFFFFF",
            highlight_color=self.highlight_color.text().strip() or "#FFD400",
            outline=self.outline_spin.value(),
            shadow=self.shadow_spin.value(),
            uppercase=self.uppercase_check.text() == "sim",
            active_scale=self.active_scale.value(),
            pop_animation=self.active_scale.value() > 115,
            pop_overshoot=10,
            pop_duration_ms=140,
            caption_vertical_position=self.position_spin.value(),
            max_words_per_chunk=self.max_words.value(),
            max_chunk_duration=self.max_duration.value(),
            strip_punctuation=True,
            callout_font_name="Archivo Black",
            callout_color=self.highlight_color.text().strip() or "#FFD400",
            callout_scale_peak=min(150, self.active_scale.value() + 10),
            callout_bounce=self.active_scale.value() > 115,
            transition_type=self.transition_combo.currentText(),
            transition_duration=self.transition_dur.value(),
            silence_gap_s=self.silence_gap.value(),
            zoom_intensity=self.zoom_intensity.value(),
            zoom_spread_s=self.zoom_spread.value(),
            max_zooms=self.max_zooms.value(),
            illustration_density_s=self.illus_density.value(),
            sfx_enabled=True,
            music_mood=self.music_mood.text().strip() or "motivacional",
            music_energy=0.6,
        )

    def _update_preview(self) -> None:
        try:
            t = self._template_from_editor("preview", "Preview", "")
            path = Path("temp/template_preview_current.png")
            generate_template_preview(t, path, width=540, height=960)
            pixmap = QPixmap(str(path))
            self.preview_label.setPixmap(
                pixmap.scaled(
                    self.preview_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        except Exception as exc:
            logger.exception("Falha ao gerar preview")
            self.preview_label.setText(f"Erro no preview:\n{exc}")

    def _save_as_new(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Novo template", "Nome do novo template:")
        if not ok or not name.strip():
            return
        tid = name.strip().lower().replace(" ", "_").replace("-", "_")
        if self.manager.get(tid) is not None:
            QMessageBox.warning(self, "Nome em uso", "Já existe um template com esse nome.")
            return
        t = self._template_from_editor(tid, name.strip(), "Template customizado pelo usuário.")
        self.manager.save_custom(t)
        self._populate_combo()
        self.combo.setCurrentIndex(self.combo.findData(tid))
        QMessageBox.information(self, "Salvo", f"Template '{name.strip()}' salvo.")

    def _delete_custom(self) -> None:
        tid = self.combo.currentData()
        if tid not in self.manager._custom:
            return
        reply = QMessageBox.question(
            self,
            "Excluir",
            "Tem certeza que deseja excluir este template customizado?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.manager.delete_custom(tid)
            self._populate_combo()

    def _apply_and_close(self) -> None:
        tid = self.combo.currentData()
        t = self.manager.get(tid)
        if t is None:
            return
        # Se o usuário editou o template, usa os valores atuais do editor
        if tid in self.manager._custom:
            t = self._template_from_editor(tid, t.name, t.description)
            self.manager.save_custom(t)
        apply_template(self.settings, t)
        self.settings.active_template_id = t.id
        self.settings.save()
        self.selected_template = t
        self.accept()
