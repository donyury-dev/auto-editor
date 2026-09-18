"""Tela de revisão do plano de edição (obrigatória na Fase 2 e Ilustrações).

A IA (ou heurística) sugere cortes, zooms, transições e ilustrações; o
usuário vê cada sugestão, edita tempos/prompts, aprova/rejeita
individualmente e troca imagens. Nada é renderizado sem passar por aqui.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.edit_plan import TRANSITION_TYPES, EditPlan
from core.illustration_plan import IllustrationMoment

logger = logging.getLogger(__name__)

THUMB_SIZE = 96


class ReviewDialog(QDialog):
    """Revisão das sugestões antes da renderização final."""

    def __init__(
        self,
        plan: EditPlan,
        illustrations: list[IllustrationMoment] | None = None,
        image_fetcher=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.plan = plan
        self.illustrations = list(illustrations or [])
        # callable(prompt) -> Path da imagem (manager.fetch_cached)
        self._image_fetcher = image_fetcher
        self.setWindowTitle("Revisar sugestões de edição")
        self.setMinimumSize(820, 560)

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Plano gerado por: <b>{plan.source}</b> — revise, ajuste e "
            "approve o que quiser. Nada é renderizado sem sua aprovação."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # ------------------------------------------------------------------
        # Aba 1: cortes e zooms
        # ------------------------------------------------------------------
        cuts_tab = QWidget()
        cuts_layout = QVBoxLayout(cuts_tab)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Tipo", "Início (s)", "Fim (s)", "Motivo", "Aprovar"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        cuts_layout.addWidget(self.table)

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
        cuts_layout.addLayout(controls)
        self.tabs.addTab(cuts_tab, "Cortes e zooms")

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
        # Aba 2: ilustrações (B-roll)
        # ------------------------------------------------------------------
        illus_tab = QWidget()
        illus_layout = QVBoxLayout(illus_tab)

        illus_hint = QLabel(
            "Ilustrações sugeridas sobre a fala. Ajuste tempos/prompt, "
            "busque outra imagem ou desmarque para remover."
        )
        illus_hint.setWordWrap(True)
        illus_layout.addWidget(illus_hint)

        self.illus_table = QTableWidget(0, 5)
        self.illus_table.setHorizontalHeaderLabels(
            ["Imagem", "Início (s)", "Fim (s)", "Prompt", "Aprovar"]
        )
        self.illus_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self.illus_table.setIconSize(
            QPixmap(THUMB_SIZE, THUMB_SIZE).size()
        )
        illus_layout.addWidget(self.illus_table, 1)

        illus_buttons = QHBoxLayout()
        swap_btn = QPushButton("Buscar outra imagem (prompt ao lado)")
        swap_btn.clicked.connect(self._regenerate_image)
        illus_buttons.addWidget(swap_btn)
        illus_buttons.addStretch(1)
        illus_layout.addLayout(illus_buttons)
        self.tabs.addTab(illus_tab, "Ilustrações")

        self._illus_rows: list[dict] = []
        for m in self.illustrations:
            self._add_illus_row(m)

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
    # Montagem das tabelas
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

    def _add_illus_row(self, moment: IllustrationMoment) -> None:
        row = self.illus_table.rowCount()
        self.illus_table.insertRow(row)
        self.illus_table.setRowHeight(row, THUMB_SIZE + 8)

        icon_item = QTableWidgetItem()
        if moment.image_path:
            icon = QIcon(str(moment.image_path))
            if not icon.isNull():
                icon_item.setIcon(icon)
        icon_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.illus_table.setItem(row, 0, icon_item)

        for col, value in ((1, moment.start), (2, moment.end)):
            item = QTableWidgetItem(f"{value:.2f}")
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            )
            self.illus_table.setItem(row, col, item)

        prompt_item = QTableWidgetItem(moment.prompt)
        prompt_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
        )
        self.illus_table.setItem(row, 3, prompt_item)

        checkbox = QCheckBox()
        checkbox.setChecked(bool(moment.image_path))
        checkbox.stateChanged.connect(self._update_summary)
        self.illus_table.setCellWidget(row, 4, checkbox)

        self._illus_rows.append({"row": row, "moment": moment})

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def _approve_all(self) -> None:
        self._set_all(True)

    def _reject_all(self) -> None:
        self._set_all(False)

    def _set_all(self, checked: bool) -> None:
        current = self.tabs.currentIndex()
        rows = self._rows if current == 0 else self._illus_rows
        table = self.table if current == 0 else self.illus_table
        for r in rows:
            widget = table.cellWidget(r["row"], 4)
            widget.setChecked(checked)
        self._update_summary()

    def _regenerate_image(self) -> None:
        """Busca outra imagem para a linha selecionada (usa o prompt editado)."""
        if self._image_fetcher is None:
            QMessageBox.information(
                self, "Indisponível", "Nenhuma fonte de imagem configurada."
            )
            return
        selected = self.illus_table.selectedItems()
        if not selected:
            QMessageBox.information(
                self, "Selecione", "Selecione uma linha da tabela."
            )
            return
        row = selected[0].row()
        prompt_item = self.illus_table.item(row, 3)
        prompt = (prompt_item.text() if prompt_item else "").strip()
        if not prompt:
            QMessageBox.warning(self, "Prompt vazio", "Edite o prompt antes.")
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            path = self._image_fetcher(prompt)
        except Exception as exc:
            logger.exception("Busca de imagem falhou")
            QMessageBox.critical(self, "Falhou", f"Busca de imagem: {exc}")
            return
        finally:
            self.unsetCursor()

        for r in self._illus_rows:
            if r["row"] == row:
                r["moment"].prompt = prompt
                r["moment"].image_path = path
                icon_item = self.illus_table.item(row, 0)
                icon_item.setIcon(QIcon(str(path)))
                checkbox = self.illus_table.cellWidget(row, 4)
                checkbox.setChecked(True)
                break

    def _read_cell_time(self, row: int, col: int, fallback: float, table=None) -> float:
        table = table or self.table
        item = table.item(row, col)
        if item is None:
            return fallback
        try:
            return max(0.0, float(item.text().replace(",", ".")))
        except ValueError:
            return fallback

    def _collect_and_accept(self) -> None:
        """Reconstrói o plano e as ilustrações com o que foi aprovado."""
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

        approved_illus: list[IllustrationMoment] = []
        for r in self._illus_rows:
            checkbox = self.illus_table.cellWidget(r["row"], 4)
            moment = r["moment"]
            if not checkbox.isChecked():
                continue
            start = self._read_cell_time(
                r["row"], 1, moment.start, table=self.illus_table
            )
            end = self._read_cell_time(
                r["row"], 2, moment.end, table=self.illus_table
            )
            prompt_item = self.illus_table.item(r["row"], 3)
            if prompt_item is not None and prompt_item.text().strip():
                moment.prompt = prompt_item.text().strip()
            if end <= start or not moment.image_path:
                continue
            moment.start, moment.end = start, end
            approved_illus.append(moment)
        self.illustrations = approved_illus

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

        approved_illus = 0
        for r in self._illus_rows:
            checkbox = self.illus_table.cellWidget(r["row"], 4)
            if checkbox and checkbox.isChecked():
                approved_illus += 1

        final = max(0.0, self.plan.duration - total_cut)
        self.summary.setText(
            f"{approved_cuts} corte(s), {approved_zooms} zoom(s) e "
            f"{approved_illus} ilustração(ões) aprovados — "
            f"duração: {self.plan.duration:.1f}s → {final:.1f}s "
            f"(−{total_cut:.1f}s) • transição: "
            f"{self.transition_combo.currentText()}"
        )

    def approved_plan(self) -> EditPlan:
        """Plano com apenas as sugestões aprovadas (após accept())."""
        return self.plan

    def approved_illustrations(self) -> list[IllustrationMoment]:
        """Ilustrações aprovadas (após accept())."""
        return self.illustrations
