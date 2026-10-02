"""Tela de revisão didática e leve.

Layout simples:
- player grande com vídeo + áudio no topo
- barra de timeline com cortes vermelhos, playhead e botões
- lista pequena dos cortes com início/fim/remover e "+ Corte aqui"

Substitui a experiência confusa do editor CapCut por algo próximo do
que o usuário já conhece (YouTube Studio, CapCut na versão simplificada).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.audio_plan import AudioPlan
from core.edit_plan import Cut, EditPlan, ZoomEffect
from core.illustration_plan import IllustrationMoment
from core.pack_manager import PackManager, PackSuggestion
from ui.preview_widget import EditedPreviewWidget
from ui.timeline_widget import EditTimelineWidget

logger = logging.getLogger(__name__)


class ReviewDialog(QDialog):
    """Diálogo de revisão simplificado: cortes visíveis e editáveis."""

    def __init__(
        self,
        plan: EditPlan,
        illustrations: list[IllustrationMoment] | None = None,
        image_fetcher=None,
        audio_plan: AudioPlan | None = None,
        music_tracks=None,
        pack_suggestions=None,
        pack_manager=None,
        video_path=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Revisar cortes")
        self.resize(960, 720)
        self.setModal(True)

        self.plan = plan
        self.illustrations = list(illustrations or [])
        self._image_fetcher = image_fetcher
        self.audio_plan = audio_plan or AudioPlan()
        self._music_tracks = list(music_tracks or [])
        self.pack_suggestions = list(pack_suggestions or [])
        self._pack_manager = pack_manager
        self._video_path = Path(video_path) if video_path else None

        # cópia editável dos cortes e zooms
        self._cuts: list[Cut] = [
            Cut(c.start, c.end, c.reason) for c in plan.cuts
        ]
        self._zooms: list[ZoomEffect] = [
            ZoomEffect(z.start, z.end, z.intensity, z.reason)
            for z in plan.zooms
        ]

        self._build_ui()
        if self._video_path:
            self.preview.load(self._video_path)
            self.preview.set_cut_simulation(True, self._cuts_for_preview())
        self._populate_table()
        self._update_summary()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # instrução
        hint = QLabel(
            "Vermelho = trecho que será removido. "
            "Arraste as bordas na barra ou ajuste os tempos na tabela. "
            "Clique em qualquer ponto para posicionar o playhead."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b8b96; font-size: 12px;")
        layout.addWidget(hint)

        # player
        self.preview = EditedPreviewWidget()
        self.preview.timeChanged.connect(self._on_preview_time_changed)
        layout.addWidget(self.preview, 1)

        # timeline simples
        self.timeline = EditTimelineWidget()
        self.timeline.set_plan(self._fake_plan())
        self.timeline.timeClicked.connect(self._on_timeline_seek)
        self.timeline.cutChanged.connect(self._on_timeline_cut_changed)
        layout.addWidget(self.timeline)

        # controles
        controls = QHBoxLayout()
        self.add_cut_btn = QPushButton("+ Corte aqui")
        self.add_cut_btn.setToolTip("Adiciona um corte começando no playhead")
        self.add_cut_btn.clicked.connect(self._add_cut_at_playhead)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play)
        self.preview_btn = QPushButton("👁 Prévia do resultado")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setChecked(True)
        self.preview_btn.toggled.connect(self._on_preview_mode_changed)
        controls.addWidget(self.add_cut_btn)
        controls.addWidget(self.play_btn)
        controls.addStretch(1)
        controls.addWidget(self.preview_btn)
        layout.addLayout(controls)

        # tabela de cortes
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Início (s)", "Fim (s)", ""])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(2, 80)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.table)

        # zooms (só leitura, para informar)
        if self._zooms:
            zoom_hint = QLabel(
                f"Zooms sugeridos: {len(self._zooms)} — "
                "aplicados automaticamente durante o render."
            )
            zoom_hint.setStyleSheet("color: #0fe0cc; font-size: 11px;")
            layout.addWidget(zoom_hint)

        # resumo
        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #8b8b96; font-size: 12px;")
        layout.addWidget(self.summary)

        # botões
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        render = QPushButton("Renderizar vídeo")
        render.setObjectName("accent")
        render.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(render)
        layout.addLayout(actions)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_play_tick)

    # ------------------------------------------------------------------
    # lógica
    # ------------------------------------------------------------------

    def _fake_plan(self) -> EditPlan:
        return EditPlan(
            cuts=self._cuts,
            zooms=self._zooms,
            duration=self.plan.duration,
            transition_type=self.plan.transition_type,
            transition_duration=self.plan.transition_duration,
        )

    def _cuts_for_preview(self) -> list[dict]:
        return [
            {"start": c.start, "end": c.end, "approved": True}
            for c in self._cuts
        ]

    def _populate_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for i, cut in enumerate(self._cuts):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, self._time_item(cut.start))
            self.table.setItem(row, 1, self._time_item(cut.end))
            btn = QPushButton("Remover")
            btn.clicked.connect(lambda _c=False, idx=i: self._remove_cut(idx))
            self.table.setCellWidget(row, 2, btn)
        self.table.blockSignals(False)
        self.timeline.set_plan(self._fake_plan())
        self.timeline.set_final_view(
            self.preview_btn.isChecked(), self.preview.display_duration()
        )

    @staticmethod
    def _time_item(value: float) -> QTableWidgetItem:
        item = QTableWidgetItem(f"{value:.2f}")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsEditable
            | Qt.ItemFlag.ItemIsSelectable
        )
        return item

    def _on_table_item_changed(self, item) -> None:
        row = item.row()
        if not (0 <= row < len(self._cuts)):
            return
        try:
            value = float(item.text().replace(",", "."))
        except ValueError:
            self._populate_table()
            return
        if item.column() == 0:
            self._cuts[row].start = max(0.0, value)
        elif item.column() == 1:
            self._cuts[row].end = min(self.plan.duration, value)
        self._cuts.sort(key=lambda c: c.start)
        self._populate_table()
        self._update_summary()
        self.preview.set_cut_simulation(True, self._cuts_for_preview())

    def _add_cut_at_playhead(self) -> None:
        t = self.preview.source_time()
        end = min(t + 2.0, self.plan.duration)
        self._cuts.append(Cut(t, end, "corte manual"))
        self._cuts.sort(key=lambda c: c.start)
        self._populate_table()
        self._update_summary()
        self.preview.set_cut_simulation(True, self._cuts_for_preview())

    def _remove_cut(self, index: int) -> None:
        if 0 <= index < len(self._cuts):
            del self._cuts[index]
        self._populate_table()
        self._update_summary()
        self.preview.set_cut_simulation(True, self._cuts_for_preview())

    def _on_timeline_seek(self, t: float) -> None:
        self.preview.pause()
        if self.preview_btn.isChecked():
            self.preview.set_time(t)
        else:
            self.preview.set_source_time(t)

    def _on_timeline_cut_changed(self, index: int, start: float, end: float) -> None:
        if index < 0 or index >= len(self._cuts):
            self._populate_table()
            self._update_summary()
            self.preview.set_cut_simulation(True, self._cuts_for_preview())
            return
        self._cuts[index].start = start
        self._cuts[index].end = end
        self._populate_table()
        self._update_summary()
        self.preview.set_cut_simulation(True, self._cuts_for_preview())

    def _on_timeline_cut_clicked(self, index: int) -> None:
        self.table.selectRow(index)
        if 0 <= index < len(self._cuts):
            self.preview.set_source_time(self._cuts[index].start)

    def _on_preview_time_changed(self, t: float) -> None:
        self.timeline.set_playhead(t)

    def _on_preview_mode_changed(self, checked: bool) -> None:
        self.preview.set_cut_simulation(checked, self._cuts_for_preview())
        if checked:
            self.timeline.set_final_view(True, self.preview.display_duration())
        else:
            self.timeline.set_final_view(False)

    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.preview.pause()
            self.play_btn.setText("▶ Play")
        else:
            self._timer.start(40)
            self.preview.play()
            self.play_btn.setText("⏸ Pausar")

    def _on_play_tick(self) -> None:
        self.preview._tick()

    def _update_summary(self) -> None:
        removed = sum(c.end - c.start for c in self._cuts)
        final = self.plan.duration - removed
        self.summary.setText(
            f"{len(self._cuts)} corte(s) — "
            f"duração: {self.plan.duration:.1f}s → {max(0.0, final):.1f}s "
            f"(-{removed:.1f}s)"
        )

    # ------------------------------------------------------------------
    # saída
    # ------------------------------------------------------------------

    def approved_plan(self) -> EditPlan:
        return EditPlan(
            cuts=self._cuts,
            zooms=self._zooms,
            transition_type=self.plan.transition_type,
            transition_duration=self.plan.transition_duration,
            duration=self.plan.duration,
        )

    def approved_illustrations(self) -> list[IllustrationMoment]:
        return self.illustrations

    def approved_audio(self) -> AudioPlan:
        return self.audio_plan

    def approved_pack(self) -> list[PackSuggestion]:
        return self.pack_suggestions

    def done(self, result) -> None:  # noqa: N802
        self.preview.pause()
        self._timer.stop()
        super().done(result)
