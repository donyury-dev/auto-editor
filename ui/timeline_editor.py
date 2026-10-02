"""Editor de timeline principal (estilo CapCut).

Substitui a tela de revisão. Layout:
- esquerda: biblioteca de assets
- centro: player + controles
- direita: propriedades do clipe
- baixo: timeline multi-track
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.audio_plan import AudioPlan
from core.edit_plan import EditPlan
from core.illustration_plan import IllustrationMoment
from core.pack_manager import PackManager, PackSuggestion
from core.timeline_model import (
    Clip,
    PlanToTimelineAdapter,
    Timeline,
    TimelineToPlanAdapter,
    Track,
)
from ui.clip_properties import ClipPropertiesPanel
from ui.library_panel import LibraryPanel
from ui.preview_widget import EditedPreviewWidget
from ui.timeline_view import TimelineView

logger = logging.getLogger(__name__)


class TimelineEditor(QDialog):
    """Janela de edição de timeline (modal, substitui ReviewDialog)."""

    def __init__(
        self,
        edit_plan: EditPlan,
        illustrations: list[IllustrationMoment],
        audio_plan: AudioPlan | None,
        pack_suggestions: list[PackSuggestion],
        pack_manager: PackManager,
        video_path: Path | str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Auto Editor — Editar timeline")
        self.resize(1280, 860)
        # QDialog pode ser modal, mas vamos manter exec() compatível
        self.setModal(True)

        self.video_path = Path(video_path)
        self.pack_manager = pack_manager
        self._accepted = False

        # timeline inicial a partir dos planos aprovados
        self.timeline = PlanToTimelineAdapter(
            self.video_path, edit_plan.duration
        ).build(edit_plan, illustrations, audio_plan, pack_suggestions)

        self._selected_track: Track | None = None
        self._selected_clip: Clip | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_play_tick)

        self._build_ui()
        self._refresh_preview_effects()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # timeline_view precisa existir antes dos botões de zoom
        self.timeline_view = TimelineView(self.timeline)
        self.timeline_view.playheadMoved.connect(self._on_playhead_moved)
        self.timeline_view.clipSelected.connect(self._on_clip_selected)
        self.timeline_view.clipMoved.connect(self._on_clip_moved)
        self.timeline_view.clipResized.connect(self._on_clip_resized)
        self.timeline_view.clipDeleted.connect(self._on_clip_deleted)
        self.timeline_view.splitRequested.connect(self._on_clip_split)

        central = QWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # topo: biblioteca + player + propriedades
        top_split = QSplitter(Qt.Orientation.Horizontal)

        self.library = LibraryPanel(self.video_path, self.pack_manager)
        self.library.itemDoubleClicked.connect(self._on_library_double_click)
        top_split.addWidget(self.library)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(8, 8, 8, 8)
        center_layout.setSpacing(8)

        self.preview = EditedPreviewWidget()
        center_layout.addWidget(self.preview, 1)

        # controles de transporte
        transport = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.clicked.connect(self._toggle_play)
        self.split_btn = QPushButton("Dividir (S)")
        self.split_btn.setToolTip("Divide o clipe selecionado no playhead")
        self.split_btn.clicked.connect(self._split_at_playhead)
        self.del_btn = QPushButton("Remover (Del)")
        self.del_btn.clicked.connect(self._delete_selected)
        self.zoom_out = QPushButton("−")
        self.zoom_out.setFixedWidth(28)
        self.zoom_out.clicked.connect(lambda: self.timeline_view.set_zoom(self.timeline.zoom - 0.2))
        self.zoom_in = QPushButton("+")
        self.zoom_in.setFixedWidth(28)
        self.zoom_in.clicked.connect(lambda: self.timeline_view.set_zoom(self.timeline.zoom + 0.2))
        self.zoom_fit = QPushButton("Ajustar")
        self.zoom_fit.clicked.connect(self.timeline_view.zoom_to_fit)

        transport.addWidget(self.play_btn)
        transport.addWidget(self.split_btn)
        transport.addWidget(self.del_btn)
        transport.addStretch(1)
        transport.addWidget(QLabel("Zoom:"))
        transport.addWidget(self.zoom_out)
        transport.addWidget(self.zoom_in)
        transport.addWidget(self.zoom_fit)
        center_layout.addLayout(transport)

        top_split.addWidget(center)

        self.properties = ClipPropertiesPanel()
        self.properties.changed.connect(self._on_properties_changed)
        top_split.addWidget(self.properties)

        top_split.setSizes([200, 760, 220])
        root.addWidget(top_split, 2)

        # separador
        line = QWidget()
        line.setFixedHeight(2)
        line.setStyleSheet("background-color: #2a2a32;")
        root.addWidget(line)

        # baixo: timeline
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(8, 4, 8, 4)
        bottom_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.timeline_view)
        scroll.setStyleSheet("QScrollArea { border: none; background: #121216; }")
        bottom_layout.addWidget(scroll, 1)

        # botões de ação
        actions = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.close)
        self.render_btn = QPushButton("Renderizar vídeo")
        self.render_btn.setObjectName("accent")
        self.render_btn.clicked.connect(self._accept)
        actions.addStretch(1)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.render_btn)
        bottom_layout.addLayout(actions)

        root.addWidget(bottom, 1)

        if not self.preview.load(self.video_path):
            self.preview.clear()

    # ------------------------------------------------------------------
    # interações
    # ------------------------------------------------------------------

    def _on_library_double_click(self, kind: str, path: Path, label: str) -> None:
        """Adiciona o item no playhead na faixa apropriada."""
        t = self.timeline.playhead
        duration = 3.0
        try:
            import cv2

            cap = cv2.VideoCapture(str(path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            if frames > 0 and fps > 0:
                duration = min(10.0, frames / fps)
        except Exception:
            pass

        if kind in ("video", "overlay", "transition"):
            track = self.timeline.ensure_track("overlay", "Overlays")
            clip = Clip(
                kind="overlay" if kind != "video" else "video",
                start=t,
                end=min(t + duration, self.timeline.duration),
                source_path=path,
                meta={"name": label, "category": kind},
            )
        elif kind == "image":
            track = self.timeline.ensure_track("overlay", "Overlays")
            clip = Clip(
                kind="image",
                start=t,
                end=min(t + 4.0, self.timeline.duration),
                source_path=path,
                meta={"name": label},
            )
        elif kind in ("music", "sfx"):
            track_type = "music" if kind == "music" else "sfx"
            track = self.timeline.ensure_track(track_type, track_type.upper())
            clip = Clip(
                kind=kind,
                start=t,
                end=min(t + duration, self.timeline.duration),
                source_path=path,
                volume=0.25 if kind == "music" else 1.0,
                meta={"name": label},
            )
        elif kind == "text":
            track = self.timeline.ensure_track("text", "Texto")
            clip = Clip(
                kind="callout",
                start=t,
                end=min(t + 3.0, self.timeline.duration),
                text="TEXTO",
                meta={"name": label},
            )
        else:
            return

        track.add_clip(clip)
        self.timeline_view.refresh()
        self._refresh_preview_effects()

    def _on_playhead_moved(self, t: float) -> None:
        self.timeline.playhead = t
        self.preview.pause()
        self.preview.set_source_time(t)

    def _on_clip_selected(self, track: Track, clip: Clip) -> None:
        self._selected_track = track
        self._selected_clip = clip
        self.properties.set_clip(clip, self.timeline.duration)

    def _on_clip_moved(self, track: Track, clip: Clip, new_start: float) -> None:
        delta = new_start - clip.start
        clip.start = new_start
        clip.end += delta
        track.clips.sort(key=lambda c: c.start)
        self._refresh_preview_effects()

    def _on_clip_resized(
        self, track: Track, clip: Clip, new_start: float, new_end: float
    ) -> None:
        clip.start = new_start
        clip.end = new_end
        track.clips.sort(key=lambda c: c.start)
        self._refresh_preview_effects()

    def _on_clip_deleted(self, track: Track, clip: Clip) -> None:
        track.remove_clip(clip.id)
        self._selected_clip = None
        self.properties.set_clip(None)
        self.timeline_view.refresh()
        self._refresh_preview_effects()

    def _on_clip_split(self, track: Track, clip: Clip, t: float) -> None:
        try:
            left, right = clip.split_at(t)
        except ValueError:
            return
        track.clips.remove(clip)
        track.add_clip(left)
        track.add_clip(right)
        self.timeline_view.refresh()
        self._refresh_preview_effects()

    def _on_properties_changed(self) -> None:
        if self._selected_track:
            self._selected_track.clips.sort(key=lambda c: c.start)
        self.timeline_view.update()
        self._refresh_preview_effects()

    def _split_at_playhead(self) -> None:
        if self._selected_clip and self._selected_track:
            self._on_clip_split(
                self._selected_track, self._selected_clip, self.timeline.playhead
            )

    def _delete_selected(self) -> None:
        if self._selected_clip and self._selected_track:
            self._on_clip_deleted(self._selected_track, self._selected_clip)

    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.play_btn.setText("▶ Play")
        else:
            self._timer.start(40)  # ~25 fps
            self.play_btn.setText("⏸ Pausar")

    def _on_play_tick(self) -> None:
        step = 0.04
        self.timeline.playhead = min(
            self.timeline.duration, self.timeline.playhead + step
        )
        self.preview.set_source_time(self.timeline.playhead)
        self.timeline_view.update()

    def _refresh_preview_effects(self) -> None:
        """Sincroniza a prévia com clipes de overlay/call-out/imagem."""
        overlays: list[dict] = []
        images: list[dict] = []
        callouts: list[dict] = []
        overlay_track = self.timeline.track_by_type("overlay")
        if overlay_track:
            for c in overlay_track.clips:
                if c.kind == "overlay" and c.source_path:
                    overlays.append(
                        {"path": Path(c.source_path), "start": c.start, "end": c.end}
                    )
                elif c.kind == "image" and c.source_path:
                    images.append(
                        {"path": Path(c.source_path), "start": c.start, "end": c.end}
                    )
        text_track = self.timeline.track_by_type("text")
        if text_track:
            for c in text_track.clips:
                if c.kind == "callout":
                    callouts.append(
                        {"text": c.text, "start": c.start, "end": c.end}
                    )
        self.preview.set_overlays(overlays)
        self.preview.set_images(images)
        self.preview.set_callouts(callouts)

    # ------------------------------------------------------------------
    # saída
    # ------------------------------------------------------------------

    def approved_plan(self) -> EditPlan:
        return TimelineToPlanAdapter(self.timeline).to_edit_plan()

    def approved_illustrations(self) -> list[IllustrationMoment]:
        return TimelineToPlanAdapter(self.timeline).to_illustrations()

    def approved_audio(self) -> AudioPlan:
        return TimelineToPlanAdapter(self.timeline).to_audio_plan()

    def approved_pack(self) -> list[PackSuggestion]:
        return TimelineToPlanAdapter(self.timeline).to_pack_suggestions()

    def _accept(self) -> None:
        if not self.timeline.track_by_type("video"):
            QMessageBox.warning(
                self,
                "Sem vídeo",
                "A timeline precisa ter pelo menos um clipe de vídeo.",
            )
            return
        self._accepted = True
        self.accept()

    def is_accepted(self) -> bool:
        return self._accepted

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # repassa S/Del para a timeline
        if event.key() in (Qt.Key.Key_S, Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.timeline_view.keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.preview.pause()
        self._timer.stop()
        super().closeEvent(event)
