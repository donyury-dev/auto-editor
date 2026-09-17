"""Tela de revisão do plano de edição (obrigatória na Fase 2).

A IA (ou heurística) sugere cortes, zooms e transições; o usuário vê cada
sugestão, editou tempos, aprova/rejeita individualmente e escolhe a
transição. Nada é renderizado sem passar por aqui.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.edit_plan import TRANSITION_TYPES, EditPlan

logger = logging.getLogger(__name__)


class ReviewDialog(QDialog):
    """Revisão das sugestões antes da renderização final."""

    def __init__(self, plan: EditPlan, parent=None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Revisar sugestões de edição")
        self.setMinimumSize(760, 520)

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Plano gerado por: <b>{plan.source}</b> — revise, ajuste e "
            "approve o que quiser. Nada é renderizado sem sua aprovação."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        # ------------------------------------------------------------------
        # Tabela de sugestões (cortes e zooms)
        # ------------------------------------------------------------------
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Tipo", "Início (s)", "Fim (s)", "Motivo", "Aprovar"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table)

        self._rows: list[dict] = []
        for cut in plan.cuts:
            self._add_row("Corte", cut.start, cut.end, cut.reason, "cut", cut)
        for zoom in plan.zooms:
            self._add_row(
                "Zoom",
                zoom.start,
                zoom.end,
                f"{zoom.reason} (intensidade {zoom.intensity:.0%})",
                "zoom",
                zoom,
            )

        # ------------------------------------------------------------------
        # Controles globais
        # ------------------------------------------------------------------
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Transição nos cortes:"))
        self.transition_combo = QComboBox()
        self.transition_combo.addItems(TRANSITION_TYPES)
        if plan.transition_type in TRANSITION_TYPES:
            self.transition_combo.setCurrentText(plan.transition_type)
        self.transition_combo.currentTextChanged.connect(self._update_summary)
        controls.addWidget(self.transition_combo)

        controls.addWidget(QLabel("Duração (s):"))
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 1.0)
        self.duration_spin.setSingleStep(0.1)
        self.duration_spin.setValue(plan.transition_duration)
        self.duration_spin.valueChanged.connect(self._update_summary)
        controls.addWidget(self.duration_spin)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self.summary)

        # ------------------------------------------------------------------
        # Botões
        # ------------------------------------------------------------------
        buttons = QHBoxLayout()
        approve_all = QPushButton("Aprovar tudo")
        reject_all = QPushButton("Rejeitar tudo")
        cancel = QPushButton("Cancelar")
        render = QPushButton("Renderizar vídeo")
        render.setStyleSheet("font-weight: bold;")
        approve_all.clicked.connect(self._approve_all)
        reject_all.clicked.connect(self._reject_all)
        cancel.clicked.connect(self.reject)
        render.clicked.connect(self._collect_and_accept)
        buttons.addWidget(approve_all)
        buttons.addWidget(reject_all)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(render)
        layout.addLayout(buttons)

        self._update_summary()

    # ------------------------------------------------------------------
    # Montagem da tabela
    # ------------------------------------------------------------------

    def _add_row(
        self,
        kind: str,
        start: float,
        end: float,
        reason: str,
        tag: str,
        original,
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        kind_item = QTableWidgetItem(kind)
        kind_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 0, kind_item)

        for col, value in ((1, start), (2, end)):
            item = QTableWidgetItem(f"{value:.2f}")
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            )
            self.table.setItem(row, col, item)

        reason_item = QTableWidgetItem(reason)
        reason_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 3, reason_item)

        checkbox = QCheckBox()
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(self._update_summary)
        self.table.setCellWidget(row, 4, checkbox)

        self._rows.append(
            {
                "tag": tag,
                "row": row,
                "orig_start": start,
                "orig_end": end,
                "original": original,
            }
        )

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def _approve_all(self) -> None:
        self._set_all(True)

    def _reject_all(self) -> None:
        self._set_all(False)

    def _set_all(self, checked: bool) -> None:
        for r in self._rows:
            widget = self.table.cellWidget(r["row"], 4)
            widget.setChecked(checked)
        self._update_summary()

    def _read_cell_time(self, row: int, col: int, fallback: float) -> float:
        item = self.table.item(row, col)
        if item is None:
            return fallback
        try:
            return max(0.0, float(item.text().replace(",", ".")))
        except ValueError:
            return fallback

    def _collect_and_accept(self) -> None:
        """Reconstrói o plano com apenas as sugestões aprovadas."""
        from core.edit_plan import Cut, ZoomEffect, validate_plan

        cuts: list[Cut] = []
        zooms: list[ZoomEffect] = []
        for r in self._rows:
            checkbox = self.table.cellWidget(r["row"], 4)
            if not checkbox.isChecked():
                continue
            start = self._read_cell_time(r["row"], 1, r["orig_start"])
            end = self._read_cell_time(r["row"], 2, r["orig_end"])
            if end <= start:
                continue  # edição manual inválida: descarta
            original = r["original"]
            if r["tag"] == "cut":
                cuts.append(
                    Cut(start=start, end=end, reason=original.reason)
                )
            else:
                zooms.append(
                    ZoomEffect(
                        start=start,
                        end=end,
                        intensity=original.intensity,
                        reason=original.reason,
                    )
                )

        self.plan.cuts = cuts
        self.plan.zooms = zooms
        self.plan.transition_type = self.transition_combo.currentText()
        self.plan.transition_duration = self.duration_spin.value()
        self.plan = validate_plan(self.plan)
        self.accept()

    # ------------------------------------------------------------------
    # Resumo
    # ------------------------------------------------------------------

    def _update_summary(self) -> None:
        total_cut = 0.0
        approved_cuts = approved_zooms = 0
        for r in self._rows:
            checkbox = self.table.cellWidget(r["row"], 4)
            if not checkbox.isChecked():
                continue
            start = self._read_cell_time(r["row"], 1, r["orig_start"])
            end = self._read_cell_time(r["row"], 2, r["orig_end"])
            if r["tag"] == "cut":
                approved_cuts += 1
                total_cut += max(0.0, end - start)
            else:
                approved_zooms += 1
        final = max(0.0, self.plan.duration - total_cut)
        self.summary.setText(
            f"{approved_cuts} corte(s) e {approved_zooms} zoom(s) aprovados — "
            f"duração: {self.plan.duration:.1f}s → {final:.1f}s "
            f"(−{total_cut:.1f}s) • transição: "
            f"{self.transition_combo.currentText()}"
        )

    def approved_plan(self) -> EditPlan:
        """Plano com apenas as sugestões aprovadas (após accept())."""
        return self.plan
