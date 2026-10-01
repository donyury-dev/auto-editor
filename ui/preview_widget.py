"""Preview de vídeo ao vivo (simulado) — Fase 7.

Mostra o vídeo de origem com play/pause e slider: o usuário acompanha
o material que está sendo editado sem abrir um player externo.
Simulação leve: decodifica frames com OpenCV já embutido no app.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

TICK_MS = 40  # ~25 fps de atualização da simulação


class LivePreviewWidget(QWidget):
    """Player mínimo: mostra frames do vídeo de origem."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cap = None
        self._fps = 30.0
        self._duration = 0.0
        self._playing = False
        self._min_width = 320

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.canvas = QLabel("Nenhum vídeo carregado")
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumSize(self._min_width, 180)
        self.canvas.setStyleSheet(
            "background-color: #121216; border-radius: 8px; color: #666;"
        )
        layout.addWidget(self.canvas, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(44)
        self.play_btn.clicked.connect(self.toggle_play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._on_slider)
        self.time_label = QLabel("0.0s")
        self.time_label.setStyleSheet("color: #8b8b96; font-size: 11px;")
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------

    def load(self, video_path: Path | str) -> bool:
        """Abre o vídeo para preview. Retorna True se conseguiu."""
        import cv2

        self.stop()
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("Preview: não abriu %s", video_path)
            return False
        self._cap = cap
        self._fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self._duration = frames / self._fps if self._fps > 0 else 0.0
        self.slider.setRange(0, max(1, int(self._duration * 1000)))
        self.set_time(0.0)
        return True

    def clear(self) -> None:
        self.stop()
        self.canvas.setText("Nenhum vídeo carregado")

    def toggle_play(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self._cap is None:
            return
        self._playing = True
        self.play_btn.setText("⏸")
        self._timer.start()

    def pause(self) -> None:
        self._playing = False
        self.play_btn.setText("▶")
        self._timer.stop()

    def stop(self) -> None:
        self.pause()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.slider.setRange(0, 0)
        self.time_label.setText("0.0s")

    def set_time(self, seconds: float) -> None:
        """Busca o frame no tempo dado (segundos) e exibe."""
        if self._cap is None:
            return
        import cv2

        seconds = max(0.0, min(seconds, self._duration))
        self._cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        ok, frame = self._cap.read()
        if ok:
            self._show_frame(frame)
        self.time_label.setText(f"{seconds:.1f}s")
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(seconds * 1000))
            self.slider.blockSignals(False)

    def seek_fraction(self, fraction: float) -> None:
        """Posiciona o preview em fração da duração (0.0–1.0).

        Usado para acompanhar a renderização em tempo real: o frame
        exibido corresponde ao ponto do vídeo sendo renderizado.
        """
        if self._cap is None or self._duration <= 0:
            return
        self.set_time(max(0.0, min(1.0, fraction)) * self._duration)

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Avança ~1 frame por tick (simulação de tempo real)."""
        if self._cap is None:
            self.pause()
            return
        ok, frame = self._cap.read()
        if not ok:
            self.pause()
            return
        self._show_frame(frame)
        import cv2

        msec = self._cap.get(cv2.CAP_PROP_POS_MSEC)
        self.time_label.setText(f"{msec / 1000.0:.1f}s")
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(msec))
            self.slider.blockSignals(False)

    def _on_slider(self, value: int) -> None:
        self.set_time(value / 1000.0)

    def _show_frame(self, frame) -> None:
        height, width, channels = frame.shape
        bytes_per_line = channels * width
        image = QImage(
            frame.data, width, height, bytes_per_line, QImage.Format.Format_BGR888
        )
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.canvas.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.canvas.setPixmap(scaled)
