"""Visualização da timeline multi-track (estilo CapCut).

Desenha faixas, clipes, playhead e régua de tempo. Emite sinais para
movimentação, redimensionamento, seleção e mudança do playhead.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from core.timeline_model import Clip, Timeline, Track

logger = logging.getLogger(__name__)

TRACK_HEIGHT = 52
HEADER_WIDTH = 96
RULER_HEIGHT = 28
PIXELS_PER_SECOND = 40
RESIZE_HANDLE = 6
MIN_CLIP_WIDTH = 12

TRACK_COLORS = {
    "video": "#1d3a34",
    "overlay": "#2d2a4a",
    "text": "#3a2a1d",
    "music": "#1d2d3a",
    "sfx": "#2a1d2d",
}

CLIP_COLORS = {
    "video": "#0fe0cc",
    "overlay": "#a78bfa",
    "image": "#f59e0b",
    "callout": "#facc15",
    "music": "#60a5fa",
    "sfx": "#f472b6",
    "transition": "#94a3b8",
}


class TimelineView(QWidget):
    """Widget de desenho da timeline."""

    playheadMoved = pyqtSignal(float)
    clipSelected = pyqtSignal(Track, Clip)
    clipMoved = pyqtSignal(Track, Clip, float)  # track, clip, new_start
    clipResized = pyqtSignal(Track, Clip, float, float)  # track, clip, new_start, new_end
    clipDeleted = pyqtSignal(Track, Clip)
    splitRequested = pyqtSignal(Track, Clip, float)  # track, clip, time

    def __init__(self, timeline: Timeline, parent=None) -> None:
        super().__init__(parent)
        self.timeline = timeline
        self._selected_clip_id: str | None = None
        self._drag_state: dict | None = None
        self.setMouseTracking(True)
        self._set_size()

    # ------------------------------------------------------------------
    # geometria
    # ------------------------------------------------------------------

    def _pixels_per_second(self) -> float:
        return PIXELS_PER_SECOND * self.timeline.zoom

    def _time_to_x(self, t: float) -> float:
        return HEADER_WIDTH + t * self._pixels_per_second()

    def _x_to_time(self, x: float) -> float:
        return max(0.0, (x - HEADER_WIDTH) / self._pixels_per_second())

    def _track_y(self, index: int) -> int:
        return RULER_HEIGHT + index * TRACK_HEIGHT

    def _track_at_y(self, y: float) -> tuple[int, Track] | None:
        if y < RULER_HEIGHT:
            return None
        idx = int((y - RULER_HEIGHT) // TRACK_HEIGHT)
        if 0 <= idx < len(self.timeline.tracks):
            return idx, self.timeline.tracks[idx]
        return None

    def _set_size(self) -> None:
        w = int(
            HEADER_WIDTH + self.timeline.duration * self._pixels_per_second() + 80
        )
        h = RULER_HEIGHT + len(self.timeline.tracks) * TRACK_HEIGHT + 8
        self.setMinimumSize(max(w, 400), max(h, 120))
        self.resize(max(w, 400), max(h, 120))
        self.update()

    def refresh(self) -> None:
        self._set_size()
        self.update()

    # ------------------------------------------------------------------
    # pintura
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # fundo
        painter.fillRect(self.rect(), QColor("#121216"))

        # régua
        self._draw_ruler(painter)

        # faixas e clipes
        for i, track in enumerate(self.timeline.tracks):
            self._draw_track(painter, i, track)

        # playhead
        self._draw_playhead(painter)
        painter.end()

    def _draw_ruler(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#3a3a44"), 1))
        painter.drawLine(0, RULER_HEIGHT, self.width(), RULER_HEIGHT)
        painter.setPen(QColor("#8b8b96"))
        painter.setFont(QFont("Inter", 8))
        step = max(1, int(5 / self.timeline.zoom))
        t = 0.0
        while t <= self.timeline.duration:
            x = self._time_to_x(t)
            painter.drawLine(int(x), RULER_HEIGHT - 6, int(x), RULER_HEIGHT)
            painter.drawText(
                int(x) + 2, RULER_HEIGHT - 8, f"{int(t // 60):02d}:{int(t % 60):02d}"
            )
            t += step

    def _draw_track(self, painter: QPainter, index: int, track: Track) -> None:
        y = self._track_y(index)
        # header
        painter.fillRect(0, y, HEADER_WIDTH - 4, TRACK_HEIGHT - 2, QColor("#1e1e24"))
        painter.setPen(QColor("#8b8b96"))
        painter.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        painter.drawText(8, y + 18, track.name or track.type)

        # área da faixa
        color = QColor(TRACK_COLORS.get(track.type, "#26262e"))
        painter.fillRect(
            HEADER_WIDTH, y, self.width() - HEADER_WIDTH, TRACK_HEIGHT - 2, color
        )

        # borda inferior
        painter.setPen(QPen(QColor("#2a2a32"), 1))
        painter.drawLine(0, y + TRACK_HEIGHT - 1, self.width(), y + TRACK_HEIGHT - 1)

        # clipes
        for clip in track.clips:
            self._draw_clip(painter, y, clip)

    def _draw_clip(self, painter: QPainter, track_y: int, clip: Clip) -> None:
        x0 = self._time_to_x(clip.start)
        x1 = self._time_to_x(clip.end)
        w = max(MIN_CLIP_WIDTH, x1 - x0)
        margin = 4
        rect = (
            int(x0),
            track_y + margin,
            int(w),
            TRACK_HEIGHT - 2 * margin - 2,
        )

        selected = clip.id == self._selected_clip_id
        base = QColor(CLIP_COLORS.get(clip.kind, "#64748b"))
        painter.setPen(
            QPen(QColor("#ffffff" if selected else "#00000000"), 2)
        )
        painter.setBrush(base)
        painter.drawRoundedRect(*rect, 4, 4)

        # texto
        painter.setPen(QColor("#0b0b0e"))
        painter.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        label = (clip.text or clip.kind).upper()
        fm = QFontMetrics(painter.font())
        elided = fm.elidedText(label, Qt.TextElideMode.ElideRight, rect[2] - 8)
        painter.drawText(rect[0] + 4, rect[1] + 14, elided)

        # handles de resize
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(rect[0] + 2, rect[1] + 8, 3, rect[3] - 16)
        painter.drawRect(rect[0] + rect[2] - 5, rect[1] + 8, 3, rect[3] - 16)

    def _draw_playhead(self, painter: QPainter) -> None:
        x = self._time_to_x(self.timeline.playhead)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(int(x), 0, int(x), self.height())
        painter.setBrush(QColor("#ffffff"))
        from PyQt6.QtCore import QPoint
        painter.drawPolygon(
            [QPoint(int(x) - 6, 0), QPoint(int(x) + 6, 0), QPoint(int(x), 8)]
        )

    # ------------------------------------------------------------------
    # mouse
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x = event.position().x()
        y = event.position().y()
        t = self._x_to_time(x)

        track_info = self._track_at_y(y)

        # clicou num clipe?
        if track_info is not None:
            idx, track = track_info
            for clip in track.clips:
                cx0 = self._time_to_x(clip.start)
                cx1 = self._time_to_x(clip.end)
                if cx0 - RESIZE_HANDLE <= x <= cx1 + RESIZE_HANDLE:
                    self._selected_clip_id = clip.id
                    self.clipSelected.emit(track, clip)
                    handle = "left" if x < cx0 + RESIZE_HANDLE else (
                        "right" if x > cx1 - RESIZE_HANDLE else "body"
                    )
                    self._drag_state = {
                        "action": "resize" if handle != "body" else "move",
                        "handle": handle,
                        "track": track,
                        "clip": clip,
                        "start_t": t,
                        "orig_start": clip.start,
                        "orig_end": clip.end,
                    }
                    self.update()
                    return

        # clicou na timeline/régua: move playhead
        self.timeline.playhead = min(t, self.timeline.duration)
        self.playheadMoved.emit(self.timeline.playhead)
        self._drag_state = {"action": "scrub", "track": None}
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_state is None:
            self._set_cursor(event.position().x(), event.position().y())
            return

        x = event.position().x()
        t = self._x_to_time(x)
        state = self._drag_state
        clip: Clip = state["clip"]

        if state["action"] == "scrub":
            self.timeline.playhead = min(t, self.timeline.duration)
            self.playheadMoved.emit(self.timeline.playhead)
            self.update()
            return

        if state["action"] == "move":
            delta = t - state["start_t"]
            new_start = max(0.0, state["orig_start"] + delta)
            # preview visual imediato
            clip.start = new_start
            clip.end = new_start + (state["orig_end"] - state["orig_start"])
            self.update()
            return

        if state["action"] == "resize":
            if state["handle"] == "left":
                new_start = min(t, state["orig_end"] - 0.1)
                clip.start = max(0.0, new_start)
            else:
                new_end = max(t, state["orig_start"] + 0.1)
                clip.end = min(self.timeline.duration, new_end)
            self.update()
            return

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_state is None:
            return
        state = self._drag_state
        clip: Clip = state["clip"]
        track: Track = state["track"]

        if state["action"] == "move":
            self.clipMoved.emit(track, clip, clip.start)
        elif state["action"] == "resize":
            self.clipResized.emit(track, clip, clip.start, clip.end)

        self._drag_state = None
        self.update()

    def _set_cursor(self, x: float, y: float) -> None:
        track_info = self._track_at_y(y)
        if track_info is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        _idx, track = track_info
        for clip in track.clips:
            cx0 = self._time_to_x(clip.start)
            cx1 = self._time_to_x(clip.end)
            if cx0 - RESIZE_HANDLE <= x <= cx1 + RESIZE_HANDLE:
                if x < cx0 + RESIZE_HANDLE or x > cx1 - RESIZE_HANDLE:
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                else:
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                return
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_S and self._selected_clip_id:
            clip, track = self._find_clip(self._selected_clip_id)
            if clip and track and track.start < self.timeline.playhead < clip.end:
                self.splitRequested.emit(track, clip, self.timeline.playhead)
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            clip, track = self._find_clip(self._selected_clip_id)
            if clip and track:
                self.clipDeleted.emit(track, clip)
        else:
            super().keyPressEvent(event)

    def _find_clip(self, clip_id: str | None) -> tuple[Clip | None, Track | None]:
        if clip_id is None:
            return None, None
        for track in self.timeline.tracks:
            for c in track.clips:
                if c.id == clip_id:
                    return c, track
        return None, None

    def select_clip(self, clip_id: str) -> None:
        self._selected_clip_id = clip_id
        self.update()

    def set_playhead(self, t: float) -> None:
        self.timeline.playhead = max(0.0, min(t, self.timeline.duration))
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.timeline.zoom = max(0.2, min(zoom, 5.0))
        self.refresh()

    def zoom_to_fit(self) -> None:
        if self.timeline.duration > 0:
            self.timeline.zoom = max(
                0.2, (self.width() - HEADER_WIDTH - 40) / (self.timeline.duration * PIXELS_PER_SECOND)
            )
            self.refresh()

    def ensure_visible(self, t: float) -> None:
        # Futuro: scroll horizontal para centralizar t.
        pass
