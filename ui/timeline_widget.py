"""Timeline visual dos cortes/zooms na revisão (estilo CapCut).

Desenha a linha do tempo inteira do vídeo: regiões vermelhas = cortes
aprovados, contorno = cortes rejeitados, marcadores verdes = zooms.
Clicar numa região seleciona a linha correspondente na tabela, para
ajuste manual dos tempos.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class EditTimelineWidget(QWidget):
    """Barra de timeline com cortes e zooms do plano."""

    cutClicked = pyqtSignal(int)  # índice do corte clicado
    timeClicked = pyqtSignal(float)  # tempo (s) clicado na barra
    cutChanged = pyqtSignal(int, float, float)  # índice, start, end

    HEIGHT = 56
    MARGIN = 8
    HANDLE_W = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._cuts: list[dict] = []  # {start, end, approved}
        self._zooms: list[dict] = []  # {start}
        self._playhead: float | None = None
        self._final_view = False
        self._final_duration = 0.0
        self._drag_index: int | None = None
        self._drag_edge: str | None = None  # 'left'/'right'/'move'
        self._drag_start_x = 0.0
        self._drag_orig_start = 0.0
        self._drag_orig_end = 0.0
        self.setMinimumHeight(self.HEIGHT)
        self.setMaximumHeight(self.HEIGHT)
        self.setMouseTracking(True)

    def set_plan(self, plan) -> None:
        self._duration = max(0.1, float(getattr(plan, "duration", 0.0) or 0.0))
        self._cuts = [
            {
                "start": float(c.start),
                "end": float(c.end),
                "approved": bool(getattr(c, "approved", True)),
            }
            for c in plan.cuts
        ]
        self._zooms = [
            {"start": float(z.start), "approved": bool(getattr(z, "approved", True))}
            for z in getattr(plan, "zooms", [])
        ]
        self.update()

    def set_cuts(self, cuts: list[dict]) -> None:
        """Atualiza só os cortes (edição manual na tabela)."""
        self._cuts = [dict(c) for c in cuts]
        self.update()

    def set_playhead(self, seconds: float) -> None:
        """Move o cursor de tempo (sincronizado com o preview de vídeo)."""
        limit = self._final_duration if self._final_view else self._duration
        self._playhead = max(0.0, min(seconds, limit))
        self.update()

    def set_final_view(self, enabled: bool, final_duration: float = 0.0) -> None:
        """Modo 'vídeo final': trechos cortados desaparecem da barra.

        Nesse modo os tempos clicados/exibidos são do vídeo final.
        """
        self._final_view = bool(enabled)
        self._final_duration = max(0.1, final_duration or self._duration)
        self.update()

    def refresh_cut(self, index: int, start: float, end: float, approved: bool) -> None:
        if 0 <= index < len(self._cuts):
            self._cuts[index].update(
                start=start, end=end, approved=approved
            )
            self.update()

    # ------------------------------------------------------------------

    def _time_to_x(self, t: float) -> float:
        duration = self._final_duration if self._final_view else self._duration
        usable = self.width() - 2 * self.MARGIN
        return self.MARGIN + (t / max(0.1, duration)) * usable

    def _x_to_time(self, x: float) -> float:
        duration = self._final_duration if self._final_view else self._duration
        usable = self.width() - 2 * self.MARGIN
        return max(0.0, min(1.0, (x - self.MARGIN) / usable)) * duration

    def mousePressEvent(self, event) -> None:  # noqa: N802 (API Qt)
        pos = event.position()
        x = float(pos.x())
        t = self._x_to_time(x)
        self.timeClicked.emit(t)
        if self._final_view:
            return
        for i, cut in enumerate(self._cuts):
            x1 = self._time_to_x(cut["start"])
            x2 = self._time_to_x(cut["end"])
            if not (x1 <= x <= x2):
                continue
            self.cutClicked.emit(i)
            if abs(x - x1) <= self.HANDLE_W:
                self._drag_edge = "left"
            elif abs(x - x2) <= self.HANDLE_W:
                self._drag_edge = "right"
            else:
                self._drag_edge = "move"
            self._drag_index = i
            self._drag_start_x = x
            self._drag_orig_start = cut["start"]
            self._drag_orig_end = cut["end"]
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self._final_view:
            return
        x = float(event.position().x())
        t = self._x_to_time(x)
        if self._drag_index is not None:
            dt = t - self._x_to_time(self._drag_start_x)
            i = self._drag_index
            orig_s = self._drag_orig_start
            orig_e = self._drag_orig_end
            if self._drag_edge == "left":
                self._cuts[i]["start"] = max(0.0, min(orig_e - 0.2, orig_s + dt))
            elif self._drag_edge == "right":
                self._cuts[i]["end"] = min(
                    self._duration, max(orig_s + 0.2, orig_e + dt)
                )
            elif self._drag_edge == "move":
                span = orig_e - orig_s
                new_s = max(0.0, min(self._duration - span, orig_s + dt))
                self._cuts[i]["start"] = new_s
                self._cuts[i]["end"] = new_s + span
            self.update()
            self.cutChanged.emit(
                i, self._cuts[i]["start"], self._cuts[i]["end"]
            )
            return
        # cursor de resize
        over_handle = False
        for cut in self._cuts:
            x1 = self._time_to_x(cut["start"])
            x2 = self._time_to_x(cut["end"])
            if x1 - self.HANDLE_W <= x <= x1 + self.HANDLE_W or \
               x2 - self.HANDLE_W <= x <= x2 + self.HANDLE_W:
                over_handle = True
                break
        self.setCursor(
            QCursor(Qt.CursorShape.SizeHorCursor if over_handle else Qt.CursorShape.ArrowCursor)
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (API Qt)
        if self._drag_index is not None:
            self._drag_index = None
            self._drag_edge = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.cutChanged.emit(-1, 0.0, 0.0)

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        # fundo
        painter.setBrush(QColor("#26262e"))
        bar = QRectF(
            self.MARGIN, 18, self.width() - 2 * self.MARGIN, 20
        )
        painter.drawRect(bar)

        if self._final_view:
            # vídeo final: uma faixa contínua — o que foi cortado sumiu
            painter.setBrush(QColor("#1d3a34"))
            painter.drawRect(bar)
            self._draw_playhead_and_labels(painter)
            return

        # regiões mantidas (entre cortes) em verde escuro sutil
        painter.setBrush(QColor("#1d3a34"))
        cursor = 0.0
        for cut in sorted(self._cuts, key=lambda c: c["start"]):
            if cut["start"] > cursor:
                painter.drawRect(
                    QRectF(
                        self._time_to_x(cursor), 18,
                        self._time_to_x(cut["start"]) - self._time_to_x(cursor), 20,
                    )
                )
            cursor = max(cursor, cut["end"])
        if cursor < self._duration:
            painter.drawRect(
                QRectF(
                    self._time_to_x(cursor), 18,
                    self._time_to_x(self._duration) - self._time_to_x(cursor), 20,
                )
            )

        # cortes (removidos): vermelho se aprovado, contorno se rejeitado
        for cut in self._cuts:
            rect = QRectF(
                self._time_to_x(cut["start"]), 18,
                max(2.0, self._time_to_x(cut["end"]) - self._time_to_x(cut["start"])),
                20,
            )
            if cut["approved"]:
                painter.setBrush(QColor("#8a3040"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(rect)
            else:
                painter.setBrush(QColor("#3a2030"))
                painter.setPen(QPen(QColor("#a04858"), 1))
                painter.drawRect(rect)

        # marcadores de zoom
        painter.setPen(Qt.PenStyle.NoPen)
        for zoom in self._zooms:
            x = self._time_to_x(zoom["start"])
            painter.setBrush(QColor("#0fe0cc") if zoom["approved"] else QColor("#3a5a56"))
            painter.drawRect(QRectF(x - 1.5, 8, 3, 40))

        self._draw_playhead_and_labels(painter)

    def _draw_playhead_and_labels(self, painter: QPainter) -> None:
        # playhead (sincronizado com o preview)
        if self._playhead is not None:
            x = self._time_to_x(self._playhead)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawLine(
                int(x), 10, int(x), self.height() - 18
            )

        # rótulos de tempo
        painter.setPen(QColor("#8b8b96"))
        painter.drawText(
            QRectF(0, self.height() - 16, self.width(), 14),
            Qt.AlignmentFlag.AlignLeft,
            "0:00",
        )
        painter.drawText(
            QRectF(0, self.height() - 16, self.width() - self.MARGIN, 14),
            Qt.AlignmentFlag.AlignRight,
            self._format(
                self._final_duration if self._final_view else self._duration
            ),
        )
        painter.end()

    @staticmethod
    def _format(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        return f"{m}:{s:02d}"
