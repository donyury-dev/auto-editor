"""Painel direito de propriedades do clipe selecionado (estilo CapCut)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.timeline_model import Clip


class ClipPropertiesPanel(QWidget):
    """Mostra e edita as propriedades do clipe selecionado."""

    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.clip: Clip | None = None
        self.setFixedWidth(220)
        self.setEnabled(False)
        self._building = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.title = QLabel("Nenhum clipe selecionado")
        self.title.setObjectName("sectionTitle")
        layout.addWidget(self.title)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.kind_label = QLabel("-")
        form.addRow("Tipo:", self.kind_label)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setDecimals(2)
        self.start_spin.setSingleStep(0.1)
        self.start_spin.setRange(0.0, 99999.0)
        self.start_spin.valueChanged.connect(self._on_change)
        form.addRow("Início (s):", self.start_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setDecimals(2)
        self.end_spin.setSingleStep(0.1)
        self.end_spin.setRange(0.0, 99999.0)
        self.end_spin.valueChanged.connect(self._on_change)
        form.addRow("Fim (s):", self.end_spin)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setRange(0.0, 1.0)
        self.opacity_spin.valueChanged.connect(self._on_change)
        form.addRow("Opacidade:", self.opacity_spin)

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setDecimals(2)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setRange(0.1, 3.0)
        self.scale_spin.valueChanged.connect(self._on_change)
        form.addRow("Escala:", self.scale_spin)

        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setDecimals(2)
        self.volume_spin.setSingleStep(0.05)
        self.volume_spin.setRange(0.0, 2.0)
        self.volume_spin.valueChanged.connect(self._on_change)
        form.addRow("Volume:", self.volume_spin)

        self.text_edit = QLineEdit()
        self.text_edit.textChanged.connect(self._on_change)
        form.addRow("Texto:", self.text_edit)

        self.anim_in = QComboBox()
        self.anim_in.addItems(["fade", "pop", "slide_left", "slide_up", "none"])
        self.anim_in.currentTextChanged.connect(self._on_change)
        form.addRow("Entrada:", self.anim_in)

        self.anim_out = QComboBox()
        self.anim_out.addItems(["fade", "pop", "slide_left", "slide_up", "none"])
        self.anim_out.currentTextChanged.connect(self._on_change)
        form.addRow("Saída:", self.anim_out)

        layout.addLayout(form)
        layout.addStretch(1)

    def set_clip(self, clip: Clip | None, duration: float = 0.0) -> None:
        self._building = True
        self.clip = clip
        self.setEnabled(clip is not None)
        if clip is None:
            self.title.setText("Nenhum clipe selecionado")
            self._building = False
            return

        self.title.setText(f"{clip.kind.upper()} — {clip.id[:6]}")
        self.kind_label.setText(clip.kind)
        self.start_spin.setRange(0.0, duration)
        self.end_spin.setRange(0.0, duration)
        self.start_spin.setValue(clip.start)
        self.end_spin.setValue(clip.end)
        self.opacity_spin.setValue(clip.opacity)
        self.scale_spin.setValue(clip.scale)
        self.volume_spin.setValue(clip.volume)
        self.text_edit.setText(clip.text)
        self.anim_in.setCurrentText(clip.animation_in)
        self.anim_out.setCurrentText(clip.animation_out)
        self._building = False

    def _on_change(self) -> None:
        if self._building or self.clip is None:
            return
        self.clip.start = self.start_spin.value()
        self.clip.end = self.end_spin.value()
        self.clip.opacity = self.opacity_spin.value()
        self.clip.scale = self.scale_spin.value()
        self.clip.volume = self.volume_spin.value()
        self.clip.text = self.text_edit.text()
        self.clip.animation_in = self.anim_in.currentText()
        self.clip.animation_out = self.anim_out.currentText()
        self.changed.emit()
