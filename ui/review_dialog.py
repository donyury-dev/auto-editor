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

from core.audio_plan import SFX_LABELS, AudioPlan
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
        audio_plan: AudioPlan | None = None,
        music_tracks=None,
        pack_suggestions=None,
        pack_manager=None,
        video_path=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.plan = plan
        self.illustrations = list(illustrations or [])
        # callable(prompt) -> Path da imagem (manager.fetch_cached)
        self._image_fetcher = image_fetcher
        self.audio_plan = audio_plan or AudioPlan()
        self._music_tracks = list(music_tracks or [])
        self.pack_suggestions = list(pack_suggestions or [])
        self._pack_manager = pack_manager
        self._video_path = video_path
        self.setWindowTitle("Revisar sugestões de edição")
        self.setMinimumSize(820, 560)

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Plano gerado por: <b>{plan.source}</b> — revise, ajuste e "
            "approve o que quiser. Nada é renderizado sem sua aprovação."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        from ui.preview_widget import EditedPreviewWidget
        from ui.timeline_widget import EditTimelineWidget

        # ------------------------------------------------------------------
        # Player compartilhado (topo): simula o VÍDEO FINAL — pula cortes
        # aprovados e compõe overlays/destaques no tempo certo.
        # ------------------------------------------------------------------
        self.preview = EditedPreviewWidget()
        self.preview.setMaximumHeight(230)
        layout.addWidget(self.preview)
        if self._video_path:
            try:
                self.preview.load(self._video_path)
            except Exception as exc:  # cv2 ausente ou arquivo ilegível
                logger.warning("Preview indisponível: %s", exc)

        sim_row = QHBoxLayout()
        self.sim_check = QCheckBox(
            "Prévia mostra o RESULTADO (pula os cortes aprovados)"
        )
        self.sim_check.setChecked(True)
        self.sim_check.stateChanged.connect(self._apply_cut_simulation)
        sim_row.addWidget(self.sim_check)
        sim_hint = QLabel(
            "— desmarque para navegar o vídeo original com as marcas"
        )
        sim_hint.setStyleSheet("color: #8b8b96; font-size: 11px;")
        sim_row.addWidget(sim_hint)
        sim_row.addStretch(1)
        layout.addLayout(sim_row)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # ------------------------------------------------------------------
        # Aba 1: cortes e zooms
        # ------------------------------------------------------------------
        cuts_tab = QWidget()
        cuts_layout = QVBoxLayout(cuts_tab)

        self.timeline = EditTimelineWidget()
        self.timeline.set_plan(plan)
        self.timeline.cutClicked.connect(self._select_cut_row)
        self.timeline.timeClicked.connect(self.preview.pause)
        self.timeline.timeClicked.connect(self.preview.set_time)
        self.preview.timeChanged.connect(self.timeline.set_playhead)
        cuts_layout.addWidget(self.timeline)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Tipo", "Início (s)", "Fim (s)", "Motivo", "Aprovar"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        cuts_layout.addWidget(self.table)

        cut_buttons = QHBoxLayout()
        add_cut_btn = QPushButton("+ Corte no ponto atual")
        add_cut_btn.setToolTip(
            "Cria um corte começando no tempo exibido no preview "
            "(você pode ajustar Início/Fim direto na tabela)"
        )
        add_cut_btn.clicked.connect(self._add_cut_at_playhead)
        remove_cut_btn = QPushButton("− Remover corte selecionado")
        remove_cut_btn.clicked.connect(self._remove_selected_cut)
        cut_buttons.addWidget(add_cut_btn)
        cut_buttons.addWidget(remove_cut_btn)
        cut_buttons.addStretch(1)
        cuts_layout.addLayout(cut_buttons)

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

        # Lista canônica e editável dos itens da aba 1 (ordem == linha).
        self._rows: list[dict] = []
        for cut in plan.cuts:
            self._rows.append(
                {
                    "tag": "cut",
                    "start": cut.start,
                    "end": cut.end,
                    "reason": cut.reason,
                    "approved": True,
                    "original": cut,
                }
            )
        for zoom in plan.zooms:
            self._rows.append(
                {
                    "tag": "zoom",
                    "start": zoom.start,
                    "end": zoom.end,
                    "reason": f"{zoom.reason} (intensidade {zoom.intensity:.0%})",
                    "approved": True,
                    "original": zoom,
                }
            )
        self._populating = False
        self.table.itemChanged.connect(self._on_cut_item_changed)
        self._populate_cut_table()

        # ------------------------------------------------------------------
        # Aba 2: destaques (imagem ou call-out)
        # ------------------------------------------------------------------
        highlights_tab = QWidget()
        highlights_layout = QVBoxLayout(highlights_tab)

        highlights_hint = QLabel(
            "Escolha por item: call-out de texto, imagem ou nenhum. "
            "CLIQUE numa linha para ver no vídeo de cima como o destaque "
            "vai aparecer (posição/tempo reais). Edite o texto e os tempos; "
            "nada entra no vídeo sem aprovação."
        )
        highlights_hint.setWordWrap(True)
        highlights_layout.addWidget(highlights_hint)

        self.illus_table = QTableWidget(0, 7)
        self.illus_table.setHorizontalHeaderLabels(
            [
                "Tipo",
                "Preview",
                "Início (s)",
                "Fim (s)",
                "Texto do destaque",
                "Prompt da imagem",
                "Aprovar",
            ]
        )
        self.illus_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.illus_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self.illus_table.setIconSize(
            QPixmap(THUMB_SIZE, THUMB_SIZE).size()
        )
        highlights_layout.addWidget(self.illus_table, 1)

        illus_buttons = QHBoxLayout()
        swap_btn = QPushButton("Buscar outra imagem (prompt ao lado)")
        swap_btn.clicked.connect(self._regenerate_image)
        illus_buttons.addWidget(swap_btn)
        illus_buttons.addStretch(1)
        highlights_layout.addLayout(illus_buttons)
        self.tabs.addTab(highlights_tab, "Destaques")

        self._illus_rows: list[dict] = []
        for m in self.illustrations:
            self._add_illus_row(m)

        # ------------------------------------------------------------------
        # Aba 3: áudio (música + efeitos sonoros)
        # ------------------------------------------------------------------
        audio_tab = QWidget()
        audio_layout = QVBoxLayout(audio_tab)

        audio_hint = QLabel(
            "Trilha sugerida pelo clima da fala"
            + (
                f" (clima detectado: <b>{self.audio_plan.mood}</b>)"
                if self.audio_plan.mood
                else ""
            )
            + ". A voz é normalizada (−16 LUFS) antes do ducking — "
            "quando há fala, a música abaixa automaticamente."
        )
        audio_hint.setWordWrap(True)
        audio_layout.addWidget(audio_hint)

        audio_form = QHBoxLayout()
        audio_form.addWidget(QLabel("Trilha:"))
        self.music_combo = QComboBox()
        self.music_combo.addItem("Sem música", None)
        current_music = str(self.audio_plan.music_path or "")
        for i, track in enumerate(self._music_tracks):
            self.music_combo.addItem(track.label, i)
            if current_music and str(track.path) == current_music:
                self.music_combo.setCurrentIndex(i + 1)
        if not self._music_tracks:
            self.music_combo.setItemText(0, "Sem música (biblioteca vazia)")
        audio_form.addWidget(self.music_combo, 1)

        audio_form.addWidget(QLabel("Volume:"))
        self.music_volume_spin = QDoubleSpinBox()
        self.music_volume_spin.setRange(0.0, 1.0)
        self.music_volume_spin.setSingleStep(0.05)
        self.music_volume_spin.setValue(self.audio_plan.music_volume)
        audio_form.addWidget(self.music_volume_spin)

        self.normalize_check = QCheckBox("Normalizar voz")
        self.normalize_check.setChecked(self.audio_plan.normalize_voice)
        self.normalize_check.stateChanged.connect(self._update_summary)
        audio_form.addWidget(self.normalize_check)
        audio_form.addWidget(QLabel("  |  "))
        self.music_play_btn = QPushButton("▶ Ouvir trilha")
        self.music_play_btn.setToolTip("Toca a trilha selecionada (prévia)")
        self.music_play_btn.clicked.connect(self._play_selected_music)
        audio_form.addWidget(self.music_play_btn)
        audio_form.addStretch(1)
        audio_layout.addLayout(audio_form)

        self.sfx_table = QTableWidget(0, 5)
        self.sfx_table.setHorizontalHeaderLabels(
            ["Efeito", "Momento (s)", "Origem", "Ouvir", "Aprovar"]
        )
        self.sfx_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        audio_layout.addWidget(self.sfx_table, 1)
        self.tabs.addTab(audio_tab, "Áudio")

        self._sfx_rows: list[dict] = []
        for event in self.audio_plan.sfx:
            self._add_sfx_row(event)

        # ------------------------------------------------------------------
        # Aba 4: pack externo (overlays, SFX, LUT da Fase 7)
        # ------------------------------------------------------------------
        pack_tab = QWidget()
        pack_layout = QVBoxLayout(pack_tab)
        pack_hint = QLabel(
            "Sugestões do seu pack externo (HD): overlay, efeito sonoro e "
            "LUT. Tudo começa DESMARCADO — clique na linha para ver o "
            "overlay no vídeo de cima no momento exato em que entraria, "
            "marque só o que combinar e troque pelo menu da linha."
        )
        pack_hint.setWordWrap(True)
        pack_layout.addWidget(pack_hint)

        self.pack_preview = QLabel("Selecione um item abaixo para pré-visualizar")
        self.pack_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pack_preview.setFixedHeight(110)
        self.pack_preview.setStyleSheet(
            "background-color: #121216; border-radius: 8px; color: #666;"
        )
        pack_layout.addWidget(self.pack_preview)

        self.pack_table = QTableWidget(0, 6)
        self.pack_table.setHorizontalHeaderLabels(
            ["Tipo", "Item do pack", "Início (s)", "Fim (s)", "Motivo", "Aprovar"]
        )
        self.pack_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        pack_layout.addWidget(self.pack_table, 1)
        self.tabs.addTab(pack_tab, "Pack")

        self._pack_rows: list[dict] = []
        for s in self.pack_suggestions:
            self._add_pack_row(s)

        # ------------------------------------------------------------------
        # Fiação da prévia composta (tabelas → player no topo)
        # ------------------------------------------------------------------
        self.illus_table.itemSelectionChanged.connect(
            self._preview_selected_illus
        )
        self.pack_table.itemSelectionChanged.connect(self._preview_selected_pack)
        self._refresh_preview_effects()
        self._apply_cut_simulation()

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

    def _populate_cut_table(self) -> None:
        """Redesenha a tabela de cortes a partir de self._rows."""
        self._populating = True
        self.table.setRowCount(0)
        for i, entry in enumerate(self._rows):
            row = self.table.rowCount()
            self.table.insertRow(row)
            entry["row"] = row

            kind_label = "Corte" if entry["tag"] == "cut" else "Zoom"
            kind_item = QTableWidgetItem(kind_label)
            kind_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, kind_item)

            for col, value in ((1, entry["start"]), (2, entry["end"])):
                item = QTableWidgetItem(f"{value:.2f}")
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
                )
                item.setToolTip("Editável: clique, digite o novo tempo e Enter")
                self.table.setItem(row, col, item)

            reason_item = QTableWidgetItem(entry["reason"])
            reason_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 3, reason_item)

            checkbox = QCheckBox()
            checkbox.setChecked(entry["approved"])
            checkbox.stateChanged.connect(
                lambda state, ix=i: self._on_cut_checkbox(ix, state)
            )
            self.table.setCellWidget(row, 4, checkbox)

        self._populating = False
        self._sync_timeline()
        self._update_summary()

    def _on_cut_checkbox(self, index: int, state) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index]["approved"] = Qt.CheckState(state) == Qt.CheckState.Checked
        self._sync_timeline()
        self._update_summary()

    def _on_cut_item_changed(self, item) -> None:
        """Tempos digitados na tabela atualizam o plano, a timeline e a prévia."""
        if self._populating or item.column() not in (1, 2):
            return
        row = item.row()
        if not (0 <= row < len(self._rows)):
            return
        entry = self._rows[row]
        try:
            value = max(0.0, float(item.text().replace(",", ".")))
        except ValueError:
            self._populate_cut_table()
            return
        key = "start" if item.column() == 1 else "end"
        entry[key] = value
        self._sync_timeline()
        self._update_summary()

    def _add_cut_at_playhead(self) -> None:
        """Novo corte começando no tempo atual do preview (vídeo original)."""
        if self.preview._cap is None:
            QMessageBox.information(
                self,
                "Sem vídeo",
                "Carregue um vídeo antes de criar cortes manuais.",
            )
            return
        start = self.preview.source_time()
        end = start + 2.0
        for entry in self._rows:
            if entry["tag"] != "cut":
                continue
            if start < entry["end"] < end:
                end = entry["end"]  # não engolir o próximo corte inteiro
        self._rows.append(
            {
                "tag": "cut",
                "start": round(start, 2),
                "end": round(end, 2),
                "reason": "corte manual (você adicionou)",
                "approved": True,
                "original": None,
            }
        )
        self._populate_cut_table()
        self.table.selectRow(len(self._rows) - 1)

    def _remove_selected_cut(self) -> None:
        selected = self.table.selectedItems()
        row = selected[0].row() if selected else self.table.currentRow()
        if not (0 <= row < len(self._rows)):
            QMessageBox.information(
                self, "Selecione", "Selecione na tabela o corte que quer remover."
            )
            return
        del self._rows[row]
        self._populate_cut_table()

    def _add_illus_row(self, moment: IllustrationMoment) -> None:
        row = self.illus_table.rowCount()
        self.illus_table.insertRow(row)
        self.illus_table.setRowHeight(row, THUMB_SIZE + 8)

        kind_combo = QComboBox()
        kind_combo.addItem("Call-out de texto", "callout")
        kind_combo.addItem("Imagem", "image")
        kind_combo.addItem("Nenhum", "none")
        kind_index = kind_combo.findData(moment.kind)
        kind_combo.setCurrentIndex(kind_index if kind_index >= 0 else 0)
        kind_combo.currentIndexChanged.connect(self._update_summary)
        kind_combo.currentIndexChanged.connect(
            lambda _ix, r=row: self._on_illus_kind_changed(r)
        )
        self.illus_table.setCellWidget(row, 0, kind_combo)

        icon_item = QTableWidgetItem("Texto" if moment.kind == "callout" else "")
        if moment.image_path:
            icon = QIcon(str(moment.image_path))
            if not icon.isNull():
                icon_item.setIcon(icon)
        icon_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.illus_table.setItem(row, 1, icon_item)

        for col, value in ((2, moment.start), (3, moment.end)):
            item = QTableWidgetItem(f"{value:.2f}")
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            )
            self.illus_table.setItem(row, col, item)

        callout_item = QTableWidgetItem(
            moment.callout_text or moment.text or moment.prompt
        )
        callout_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
        )
        self.illus_table.setItem(row, 4, callout_item)

        prompt_item = QTableWidgetItem(moment.prompt)
        prompt_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
        )
        self.illus_table.setItem(row, 5, prompt_item)

        checkbox = QCheckBox()
        checkbox.setChecked(moment.kind != "none")
        checkbox.stateChanged.connect(self._update_summary)
        self.illus_table.setCellWidget(row, 6, checkbox)

        self._illus_rows.append(
            {"row": row, "moment": moment, "kind_combo": kind_combo}
        )

    PACK_KIND_LABELS = {
        "overlay": "Overlay",
        "sfx": "Efeito sonoro",
        "lut": "LUT (cor)",
    }

    def _add_pack_row(self, suggestion) -> None:
        from core.pack_manager import PACK_CATEGORIES

        row = self.pack_table.rowCount()
        self.pack_table.insertRow(row)

        kind_item = QTableWidgetItem(
            self.PACK_KIND_LABELS.get(suggestion.kind, suggestion.kind)
        )
        kind_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.pack_table.setItem(row, 0, kind_item)

        combo = QComboBox()
        if suggestion.kind == "lut":
            combo.addItem("Nenhum", None)
            items = (
                self._pack_manager.luts() if self._pack_manager else []
            )
            for i, item in enumerate(items):
                combo.addItem(item.name, i)
        else:
            items = (
                self._pack_manager.category_items(suggestion.category)
                if self._pack_manager
                else []
            )
            for i, item in enumerate(items):
                combo.addItem(item.name, i)
        # seleciona o sugerido (casando pelo caminho)
        current_index = 0
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data is None:
                continue
            candidate = items[data]
            if str(candidate.path) == str(suggestion.path):
                current_index = i
                break
        combo.setCurrentIndex(current_index)
        combo.currentIndexChanged.connect(self._update_summary)
        combo.currentIndexChanged.connect(
            lambda _ix, r=row: self._on_pack_combo_changed(r)
        )
        self.pack_table.setCellWidget(row, 1, combo)

        for col, value in ((2, suggestion.start), (3, suggestion.end)):
            item_widget = QTableWidgetItem(f"{value:.2f}")
            item_widget.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            )
            self.pack_table.setItem(row, col, item_widget)

        category_label = PACK_CATEGORIES.get(suggestion.category, {}).get(
            "label", suggestion.category
        )
        reason_item = QTableWidgetItem(
            f"{suggestion.reason} [{category_label}]"
            if suggestion.reason
            else category_label
        )
        reason_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.pack_table.setItem(row, 4, reason_item)

        checkbox = QCheckBox()
        # conservador: começa desmarcado — o usuário vê o preview e decide
        checkbox.setChecked(False)
        checkbox.stateChanged.connect(self._update_summary)
        self.pack_table.setCellWidget(row, 5, checkbox)

        self._pack_rows.append({"row": row, "suggestion": suggestion})

    def _pack_item_for_row(self, row: int):
        """Asset atualmente selecionado no combo da linha (ou None)."""
        if not (0 <= row < len(self._pack_rows)):
            return None
        suggestion = self._pack_rows[row]["suggestion"]
        combo = self.pack_table.cellWidget(row, 1)
        if combo is None:
            return None
        data = combo.currentData()
        if data is None:
            return None
        try:
            if suggestion.kind == "lut":
                return self._pack_manager.luts()[data]
            return self._pack_manager.category_items(suggestion.category)[data]
        except (IndexError, AttributeError, TypeError):
            return None

    def _on_pack_combo_changed(self, row: int) -> None:
        """Troca de asset: atualiza a miniatura, a prévia composta e o vídeo."""
        self._update_pack_preview(row)
        self._refresh_preview_effects()
        for r in self._pack_rows:
            if r["row"] == row:
                self.preview.set_source_time(r["suggestion"].start)
                break

    def _update_pack_preview(self, row: int) -> None:
        """Mostra o primeiro frame do item selecionado (vídeo/imagem)."""
        item = self._pack_item_for_row(row)
        if item is None:
            self.pack_preview.clear()
            self.pack_preview.setText(
                "Selecione um item abaixo para pré-visualizar"
            )
            return
        pixmap = self._first_frame_pixmap(item.path)
        if pixmap is None:
            self.pack_preview.clear()
            self.pack_preview.setText(
                f"Sem preview visual ({item.path.suffix.lower() or 'arquivo'})"
            )
            return
        self.pack_preview.setPixmap(
            pixmap.scaled(
                self.pack_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @staticmethod
    def _first_frame_pixmap(path):
        """Primeiro frame de vídeo/imagem via OpenCV (None se falhar)."""
        import cv2
        from PyQt6.QtGui import QImage

        try:
            cap = cv2.VideoCapture(str(path))
            ok = False
            frame = None
            if cap.isOpened():
                ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                return None
            height, width, channels = frame.shape
            image = QImage(
                frame.data,
                width,
                height,
                channels * width,
                QImage.Format.Format_BGR888,
            )
            return QPixmap.fromImage(image)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Prévia composta: o que cada sugestão vira no vídeo
    # ------------------------------------------------------------------

    def _refresh_preview_effects(self) -> None:
        """Coleta overlays/call-outs/imagens das tabelas e manda ao player."""
        if not hasattr(self, "preview"):
            return
        overlays: list[dict] = []
        images: list[dict] = []
        callouts: list[dict] = []
        for r in self._pack_rows:
            suggestion = r["suggestion"]
            if suggestion.kind != "overlay":
                continue
            item = self._pack_item_for_row(r["row"])
            if item is None:
                continue
            start = self._read_cell_time(
                r["row"], 2, suggestion.start, table=self.pack_table
            )
            end = self._read_cell_time(
                r["row"], 3, suggestion.end, table=self.pack_table
            )
            if end > start:
                overlays.append(
                    {"path": item.path, "start": start, "end": end}
                )
        for r in self._illus_rows:
            kind = r["kind_combo"].currentData()
            moment = r["moment"]
            start = self._read_cell_time(
                r["row"], 2, moment.start, table=self.illus_table
            )
            end = self._read_cell_time(
                r["row"], 3, moment.end, table=self.illus_table
            )
            if end <= start:
                continue
            if kind == "callout":
                text_item = self.illus_table.item(r["row"], 4)
                text = (text_item.text() if text_item else "").strip()
                callouts.append(
                    {
                        "text": text or moment.callout_text or moment.prompt,
                        "start": start,
                        "end": end,
                    }
                )
            elif kind == "image" and moment.image_path:
                images.append(
                    {"path": moment.image_path, "start": start, "end": end}
                )
        self.preview.set_overlays(overlays)
        self.preview.set_callouts(callouts)
        self.preview.set_images(images)

    def _preview_selected_illus(self) -> None:
        """Clique numa linha de destaque: mostra no vídeo como vai ficar."""
        selected = self.illus_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        for r in self._illus_rows:
            if r["row"] == row:
                self.preview.pause()
                self.preview.set_source_time(r["moment"].start)
                break

    def _preview_selected_pack(self) -> None:
        selected = self.pack_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        for r in self._pack_rows:
            if r["row"] == row:
                self.preview.pause()
                self.preview.set_source_time(r["suggestion"].start)
                break

    def _on_illus_kind_changed(self, row: int) -> None:
        self._refresh_preview_effects()
        self._update_summary()
        for r in self._illus_rows:
            if r["row"] == row:
                self.preview.pause()
                self.preview.set_source_time(r["moment"].start)
                break

    # ------------------------------------------------------------------
    # Prévia de áudio
    # ------------------------------------------------------------------

    def _play_selected_music(self) -> None:
        from ui.preview_widget import play_audio_file

        selected = self.music_combo.currentData()
        if selected is None:
            QMessageBox.information(
                self, "Sem trilha", "Nenhuma trilha selecionada para ouvir."
            )
            return
        track = self._music_tracks[selected]
        error = play_audio_file(track.path)
        if error:
            QMessageBox.warning(self, "Prévia de áudio", error)

    def _play_sfx(self, row: int) -> None:
        from audio.sfx_engine import get_sfx
        from ui.preview_widget import play_audio_file

        if not (0 <= row < len(self._sfx_rows)):
            return
        event = self._sfx_rows[row]["event"]
        path = event.path
        if path is None:
            try:
                path = get_sfx(event.kind)
            except Exception as exc:
                QMessageBox.warning(self, "Prévia de áudio", str(exc))
                return
        error = play_audio_file(path)
        if error:
            QMessageBox.warning(self, "Prévia de áudio", error)

    def _add_sfx_row(self, event) -> None:
        row = self.sfx_table.rowCount()
        self.sfx_table.insertRow(row)

        kind_item = QTableWidgetItem(SFX_LABELS.get(event.kind, event.kind))
        kind_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.sfx_table.setItem(row, 0, kind_item)

        time_item = QTableWidgetItem(f"{event.timestamp:.2f}")
        time_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
        )
        self.sfx_table.setItem(row, 1, time_item)

        origin_item = QTableWidgetItem(event.origin)
        origin_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.sfx_table.setItem(row, 2, origin_item)

        play_btn = QPushButton("▶")
        play_btn.setFixedWidth(36)
        play_btn.setToolTip("Ouvir este efeito")
        play_btn.clicked.connect(lambda _c, r=row: self._play_sfx(r))
        self.sfx_table.setCellWidget(row, 3, play_btn)

        checkbox = QCheckBox()
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(self._update_summary)
        self.sfx_table.setCellWidget(row, 4, checkbox)

        self._sfx_rows.append({"row": row, "event": event})

    # ------------------------------------------------------------------
    # Ações
    # ------------------------------------------------------------------

    def _approve_all(self) -> None:
        self._set_all(True)

    def _reject_all(self) -> None:
        self._set_all(False)

    def _set_all(self, checked: bool) -> None:
        current = self.tabs.currentIndex()
        if current == 0:
            rows, table = self._rows, self.table
            checkbox_col = 4
        elif current == 1:
            rows, table = self._illus_rows, self.illus_table
            checkbox_col = 6
        elif current == 2:
            rows, table = self._sfx_rows, self.sfx_table
            checkbox_col = 4
        else:
            rows, table = self._pack_rows, self.pack_table
            checkbox_col = 5
        for r in rows:
            widget = table.cellWidget(r["row"], checkbox_col)
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
        prompt_item = self.illus_table.item(row, 5)
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
                r["moment"].kind = "image"
                r["kind_combo"].setCurrentIndex(
                    r["kind_combo"].findData("image")
                )
                icon_item = self.illus_table.item(row, 1)
                icon_item.setIcon(QIcon(str(path)))
                checkbox = self.illus_table.cellWidget(row, 6)
                checkbox.setChecked(True)
                break

    def _select_cut_row(self, index: int) -> None:
        """Clique na timeline seleciona o corte na tabela p/ ajuste manual."""
        self.tabs.setCurrentIndex(0)
        if 0 <= index < len(self._rows):
            self.table.selectRow(self._rows[index]["row"])
            entry = self._rows[index]
            if not self.sim_check.isChecked():
                # modo original: vá direto ao início da região clicada
                self.preview.set_source_time(entry["start"])

    def done(self, result) -> None:  # noqa: N802 (API Qt)
        """Solta o vídeo/áudio ao fechar a janela."""
        try:
            self.preview.pause()
            from ui.preview_widget import stop_audio

            stop_audio()
        except RuntimeError:
            pass
        super().done(result)

    def _sync_timeline(self, *args) -> None:
        """Reflete cortes/zooms (tempos/aprovação) na timeline e na prévia."""
        if not hasattr(self, "timeline"):
            return
        cuts = [
            {
                "start": r["start"],
                "end": r["end"],
                "approved": r["approved"],
            }
            for r in self._rows
        ]
        self.timeline.set_cuts(cuts)
        self._apply_cut_simulation()

    def _apply_cut_simulation(self, *args) -> None:
        """Liga/desliga a simulação do vídeo final no player e na timeline."""
        enabled = self.sim_check.isChecked()
        self.preview.set_cut_simulation(enabled, self._rows)
        if enabled:
            self.timeline.set_final_view(True, self.preview.display_duration())
        else:
            self.timeline.set_final_view(False)

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
            if not r["approved"]:
                continue
            start, end = r["start"], r["end"]
            if end <= start:
                continue  # edição manual inválida: descarta
            original = r["original"]
            if r["tag"] == "cut":
                cuts.append(
                    Cut(start=start, end=end, reason=original.reason if original else "manual")
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
            checkbox = self.illus_table.cellWidget(r["row"], 6)
            moment = r["moment"]
            if not checkbox.isChecked():
                continue
            start = self._read_cell_time(
                r["row"], 2, moment.start, table=self.illus_table
            )
            end = self._read_cell_time(
                r["row"], 3, moment.end, table=self.illus_table
            )
            kind = r["kind_combo"].currentData()
            moment.kind = kind
            callout_item = self.illus_table.item(r["row"], 4)
            if callout_item is not None:
                moment.callout_text = callout_item.text().strip()
            prompt_item = self.illus_table.item(r["row"], 5)
            if prompt_item is not None and prompt_item.text().strip():
                moment.prompt = prompt_item.text().strip()
            if end <= start or kind == "none":
                continue
            if kind == "image" and not moment.image_path:
                continue
            if kind == "callout" and not moment.callout_text:
                continue
            moment.start, moment.end = start, end
            approved_illus.append(moment)
        self.illustrations = approved_illus

        # áudio: trilha, volume, normalização e efeitos aprovados
        from core.audio_plan import SfxEvent

        selected = self.music_combo.currentData()
        if selected is None:
            self.audio_plan.music_path = None
            self.audio_plan.music_label = ""
        else:
            track = self._music_tracks[selected]
            self.audio_plan.music_path = track.path
            self.audio_plan.music_label = track.label
        self.audio_plan.music_volume = self.music_volume_spin.value()
        self.audio_plan.normalize_voice = self.normalize_check.isChecked()

        approved_sfx: list[SfxEvent] = []
        for r in self._sfx_rows:
            checkbox = self.sfx_table.cellWidget(r["row"], 4)
            if not checkbox.isChecked():
                continue
            timestamp = self._read_cell_time(
                r["row"], 1, r["event"].timestamp, table=self.sfx_table
            )
            approved_sfx.append(
                SfxEvent(
                    kind=r["event"].kind,
                    timestamp=timestamp,
                    origin=r["event"].origin,
                )
            )
        self.audio_plan.sfx = approved_sfx

        # pack: itens aprovados com o asset escolhido no combo
        from core.pack_manager import PackSuggestion

        approved_pack: list[PackSuggestion] = []
        for r in self._pack_rows:
            checkbox = self.pack_table.cellWidget(r["row"], 5)
            if not checkbox.isChecked():
                continue
            suggestion = r["suggestion"]
            combo = self.pack_table.cellWidget(r["row"], 1)
            data = combo.currentData()
            if data is None:  # LUT "Nenhum"
                continue
            chosen = (
                self._pack_manager.luts()[data]
                if suggestion.kind == "lut"
                else self._pack_manager.category_items(suggestion.category)[data]
            )
            start = self._read_cell_time(
                r["row"], 2, suggestion.start, table=self.pack_table
            )
            end = self._read_cell_time(
                r["row"], 3, suggestion.end, table=self.pack_table
            )
            approved_pack.append(
                PackSuggestion(
                    kind=suggestion.kind,
                    path=chosen.path,
                    category=chosen.category,
                    start=start,
                    end=end if end > start else suggestion.end,
                    reason=suggestion.reason,
                )
            )
        self.pack_suggestions = approved_pack

        self.accept()

    # ------------------------------------------------------------------
    # Resumo
    # ------------------------------------------------------------------

    def _update_summary(self) -> None:
        if not hasattr(self, "summary"):
            return
        total_cut = 0.0
        approved_cuts = approved_zooms = 0
        for r in self._rows:
            if not r["approved"]:
                continue
            start, end = r["start"], r["end"]
            if r["tag"] == "cut":
                approved_cuts += 1
                total_cut += max(0.0, end - start)
            else:
                approved_zooms += 1

        approved_illus = 0
        approved_callouts = 0
        approved_images = 0
        for r in self._illus_rows:
            checkbox = self.illus_table.cellWidget(r["row"], 6)
            if checkbox and checkbox.isChecked():
                kind = r["kind_combo"].currentData()
                if kind == "callout":
                    approved_callouts += 1
                elif kind == "image":
                    approved_images += 1
                approved_illus += kind != "none"

        approved_sfx = 0
        for r in self._sfx_rows:
            checkbox = self.sfx_table.cellWidget(r["row"], 3)
            if checkbox and checkbox.isChecked():
                approved_sfx += 1
        approved_pack = 0
        for r in self._pack_rows:
            checkbox = self.pack_table.cellWidget(r["row"], 5)
            if checkbox and checkbox.isChecked():
                combo = self.pack_table.cellWidget(r["row"], 1)
                if combo.currentData() is not None:
                    approved_pack += 1
        has_music = self.music_combo.currentData() is not None

        final = max(0.0, self.plan.duration - total_cut)
        self.summary.setText(
            f"{approved_cuts} corte(s), {approved_zooms} zoom(s), "
            f"{approved_callouts} call-out(s), {approved_images} imagem(ns), "
            f"{approved_illus} destaque(s), {approved_sfx} efeito(s) e "
            f"{approved_pack} item(ns) do pack aprovados — "
            f"duração: {self.plan.duration:.1f}s → {final:.1f}s "
            f"(−{total_cut:.1f}s) • transição: "
            f"{self.transition_combo.currentText()} • "
            f"música: {'sim' if has_music else 'não'}"
        )

    def approved_plan(self) -> EditPlan:
        """Plano com apenas as sugestões aprovadas (após accept())."""
        return self.plan

    def approved_illustrations(self) -> list[IllustrationMoment]:
        """Ilustrações aprovadas (após accept())."""
        return self.illustrations

    def approved_audio(self) -> AudioPlan:
        """Plano de áudio com as escolhas aprovadas (após accept())."""
        return self.audio_plan

    def approved_pack(self) -> list:
        """Sugestões do pack aprovadas (após accept())."""
        return self.pack_suggestions
