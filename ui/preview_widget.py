"""Preview de vídeo ao vivo (simulado) — Fase 7.

Mostra o vídeo de origem com play/pause e slider: o usuário acompanha
o material que está sendo editado sem abrir um player externo.
Simulação leve: decodifica frames com OpenCV já embutido no app.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
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

    timeChanged = pyqtSignal(float)  # segundos (playback e seeks)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cap = None
        self._fps = 30.0
        self._duration = 0.0
        self._playing = False
        self._min_width = 320
        self._audio_path: Path | None = None
        self._audio_proc: subprocess.Popen | None = None
        self._muted = False

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
        self.mute_btn = QPushButton("🔊")
        self.mute_btn.setFixedWidth(36)
        self.mute_btn.setToolTip("Mudo")
        self.mute_btn.clicked.connect(self._toggle_mute)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.valueChanged.connect(self._set_volume)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        controls.addWidget(self.mute_btn)
        controls.addWidget(self.vol_slider)
        layout.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------

    def load(self, video_path: Path | str) -> bool:
        """Abre o vídeo para preview e extrai áudio WAV temporário."""
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
        self._extract_audio(Path(video_path))
        self.set_time(0.0)
        return True

    def _extract_audio(self, video_path: Path) -> None:
        """Extrai áudio estéreo 48kHz para arquivo WAV temporário."""
        self._stop_audio()
        self._audio_path = None
        try:
            from core.ffmpeg_path import get_ffmpeg, subprocess_kwargs

            ffmpeg = get_ffmpeg()
            suffix = video_path.stem.replace(" ", "_")[:40]
            fd, wav_path = tempfile.mkstemp(
                prefix=f"ae_preview_{suffix}_", suffix=".wav"
            )
            os.close(fd)
            cmd = [
                str(ffmpeg),
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "48000",
                "-ac",
                "2",
                wav_path,
            ]
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                **subprocess_kwargs(),
            )
            self._audio_path = Path(wav_path)
            logger.info("Áudio de preview extraído: %s", self._audio_path)
        except Exception as exc:
            logger.warning("Não foi possível extrair áudio de preview: %s", exc)
            self._audio_path = None

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
        self._start_audio()
        self._timer.start()

    def pause(self) -> None:
        self._playing = False
        self.play_btn.setText("▶")
        self._stop_audio()
        self._timer.stop()

    def stop(self) -> None:
        self.pause()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.slider.setRange(0, 0)
        self.time_label.setText("0.0s")
        self._cleanup_audio_file()

    def _cleanup_audio_file(self) -> None:
        if self._audio_path is not None and self._audio_path.exists():
            try:
                self._audio_path.unlink()
            except OSError:
                pass
        self._audio_path = None

    def _start_audio(self) -> None:
        if self._muted or self._audio_path is None or not self._audio_path.exists():
            return
        from core.ffmpeg_path import _find_executable, subprocess_kwargs

        ffplay = _find_executable("ffplay")
        if ffplay is None:
            return
        # ffplay não tem seek preciso; começamos do tempo atual
        start = self._current_time()
        if start >= self._duration - 0.05:
            return
        self._stop_audio()
        try:
            self._audio_proc = subprocess.Popen(
                [
                    str(ffplay),
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    "-ss",
                    str(start),
                    "-volume",
                    str(self._volume_percent()),
                    str(self._audio_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **subprocess_kwargs(),
            )
        except OSError as exc:
            logger.warning("Falha ao iniciar áudio de preview: %s", exc)

    def _stop_audio(self) -> None:
        if self._audio_proc is not None:
            try:
                self._audio_proc.terminate()
                self._audio_proc.wait(timeout=0.3)
            except Exception:
                try:
                    self._audio_proc.kill()
                except Exception:
                    pass
            self._audio_proc = None

    def _volume_percent(self) -> int:
        return 0 if self._muted else self.vol_slider.value()

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        self.mute_btn.setText("🔇" if self._muted else "🔊")
        if self._playing:
            self._start_audio()

    def _set_volume(self, value: int) -> None:
        if value > 0 and self._muted:
            self._muted = False
            self.mute_btn.setText("🔊")
        if self._playing:
            self._start_audio()

    def _current_time(self) -> float:
        if self._cap is None:
            return 0.0
        import cv2

        return self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

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
        self.timeChanged.emit(seconds)
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(seconds * 1000))
            self.slider.blockSignals(False)
        if self._playing:
            self._start_audio()

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
        seconds = msec / 1000.0
        self.time_label.setText(f"{seconds:.1f}s")
        self.timeChanged.emit(seconds)
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(msec))
            self.slider.blockSignals(False)
        # Se o áudio terminou (ffplay com autoexit) e ainda estamos no fim,
        # pausamos para não ficar em loop silencioso.
        if self._audio_proc is not None and self._audio_proc.poll() is not None:
            if seconds >= self._duration - 0.2:
                self.pause()

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


# ----------------------------------------------------------------------
# Prévia do vídeo EDITADO: simula cortes, overlays e destaques
# ----------------------------------------------------------------------


class EditedPreviewWidget(LivePreviewWidget):
    """Player que simula o RESULTADO da edição.

    - Simulação de cortes: o tempo exibido é o do vídeo final; trechos
      aprovados para remoção são pulados durante o playback e nos seeks.
    - Composição: overlays do pack (blend "screen" para fundos pretos),
      imagens de destaque e call-outs de texto são desenhados sobre o
      frame no momento certo, aproximando o resultado do render FFmpeg.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cuts: list[dict] = []
        self._simulate = False
        self._kept: list[tuple[float, float, float]] = []  # (src_ini, src_fim, final_ini)
        self._final_duration = 0.0
        self._src_time = 0.0
        self._overlays: list[dict] = []  # {path, start, end}
        self._overlay_caps: dict[str, object] = {}
        self._callouts: list[dict] = []  # {text, start, end}
        self._images: list[dict] = []  # {path, start, end}

    # -- configuração ---------------------------------------------------

    def set_cut_simulation(self, enabled: bool, cuts: list[dict]) -> None:
        self._simulate = bool(enabled)
        self._cuts = list(cuts or [])
        self._rebuild_mapping()
        self._rebuild_edited_audio()
        # re-exibe o tempo atual já com o novo mapeamento
        self.set_time(self._current_display())

    def _rebuild_edited_audio(self) -> None:
        """Gera WAV editado (sem cortes aprovados) para o modo prévia."""
        self._cleanup_edited_audio()
        self._edited_audio_path: Path | None = None
        if not self._simulate or not self._cuts or self._audio_path is None:
            return
        try:
            from core.ffmpeg_path import get_ffmpeg, subprocess_kwargs

            ffmpeg = get_ffmpeg()
            fd, out_path = tempfile.mkstemp(
                prefix="ae_preview_edited_", suffix=".wav"
            )
            os.close(fd)
            inputs: list[str] = []
            for start, end, _final in self._kept:
                inputs += ["-ss", str(start), "-t", str(end - start), "-i", str(self._audio_path)]
            if not inputs:
                return
            filter_parts = []
            n = len(self._kept)
            for i in range(n):
                filter_parts.append(f"[{i}:a:0]")
            filter_parts.append(f"concat=n={n}:v=0:a=1[out]")
            cmd = [str(ffmpeg), "-y"] + inputs + ["-filter_complex", "".join(filter_parts), "-map", "[out]", out_path]
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                **subprocess_kwargs(),
            )
            self._edited_audio_path = Path(out_path)
            logger.info("Áudio editado de preview gerado: %s", self._edited_audio_path)
        except Exception as exc:
            logger.warning("Não foi possível gerar áudio editado: %s", exc)
            self._edited_audio_path = None

    def _cleanup_edited_audio(self) -> None:
        path = getattr(self, "_edited_audio_path", None)
        if path is not None and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        self._edited_audio_path = None

    def _active_audio_path(self) -> Path | None:
        if self._simulate and self._edited_audio_path is not None:
            return self._edited_audio_path
        return self._audio_path

    def _start_audio(self) -> None:
        audio_path = self._active_audio_path()
        if self._muted or audio_path is None or not audio_path.exists():
            return
        from core.ffmpeg_path import _find_executable, subprocess_kwargs

        ffplay = _find_executable("ffplay")
        if ffplay is None:
            return
        start = self._current_time()
        if self._simulate:
            # No áudio editado, o tempo de exibição já é o tempo do arquivo
            start = self._current_display()
        if start >= self.display_duration() - 0.05:
            return
        self._stop_audio()
        try:
            self._audio_proc = subprocess.Popen(
                [
                    str(ffplay),
                    "-nodisp",
                    "-autoexit",
                    "-loglevel",
                    "quiet",
                    "-ss",
                    str(start),
                    "-volume",
                    str(self._volume_percent()),
                    str(audio_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **subprocess_kwargs(),
            )
        except OSError as exc:
            logger.warning("Falha ao iniciar áudio de preview: %s", exc)

    def stop(self) -> None:
        self.pause()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.slider.setRange(0, 0)
        self.time_label.setText("0.0s")
        self._cleanup_edited_audio()
        self._cleanup_audio_file()

    def set_overlays(self, items: list[dict]) -> None:
        """items: [{path: str|Path, start: float, end: float}] (tempo original)."""
        self._overlays = list(items or [])

    def set_callouts(self, items: list[dict]) -> None:
        """items: [{text: str, start: float, end: float}] (tempo original)."""
        self._callouts = list(items or [])

    def set_images(self, items: list[dict]) -> None:
        """items: [{path: str|Path, start: float, end: float}]."""
        self._images = list(items or [])

    # -- mapeamento de tempo --------------------------------------------

    def _rebuild_mapping(self) -> None:
        cuts = sorted(
            (
                c
                for c in self._cuts
                if c.get("approved") and c["end"] > c["start"]
            ),
            key=lambda c: c["start"],
        )
        self._kept = []
        self._final_duration = 0.0
        cursor = 0.0
        final = 0.0
        for c in cuts:
            if c["start"] > cursor:
                self._kept.append((cursor, c["start"], final))
                final += c["start"] - cursor
            cursor = max(cursor, c["end"])
        if cursor < self._duration:
            self._kept.append((cursor, self._duration, final))
            final += self._duration - cursor
        self._final_duration = final

    def _src_to_final(self, t: float) -> float:
        if not self._simulate:
            return t
        for src_start, src_end, final_start in self._kept:
            if t <= src_end:
                return final_start + max(0.0, t - src_start)
        return self._final_duration

    def _final_to_src(self, t: float) -> float:
        if not self._simulate:
            return t
        for src_start, src_end, final_start in self._kept:
            seg_len = src_end - src_start
            if t <= final_start + seg_len:
                return src_start + max(0.0, t - final_start)
        return self._duration

    def _current_display(self) -> float:
        return self._src_to_final(self._src_time)

    def display_duration(self) -> float:
        return self._final_duration if self._simulate else self._duration

    # -- playback / seeks ------------------------------------------------

    def set_time(self, seconds: float) -> None:
        """Busca por tempo EXIBIDO (final quando simulando cortes)."""
        if self._cap is None:
            return
        import cv2

        seconds = max(0.0, min(seconds, self.display_duration()))
        src = self._final_to_src(seconds)
        self._seek_source(src)

    def set_source_time(self, seconds: float) -> None:
        """Busca por tempo ORIGINAL (usado ao clicar em sugestões)."""
        self._seek_source(max(0.0, min(seconds, self._duration)))

    def source_time(self) -> float:
        return self._src_time

    def _seek_source(self, src: float) -> None:
        import cv2

        src = max(0.0, min(src, self._duration))
        self._cap.set(cv2.CAP_PROP_POS_MSEC, src * 1000.0)
        ok, frame = self._cap.read()
        if ok:
            self._src_time = self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            self._show_frame(frame)
        self._after_update()

    def _after_update(self) -> None:
        display = self._current_display()
        self.time_label.setText(f"{display:.1f}s")
        self.timeChanged.emit(display)
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(display * 1000))
            self.slider.blockSignals(False)

    def _tick(self) -> None:
        import cv2

        if self._cap is None:
            self.pause()
            return
        # pulo de cortes aprovados durante o playback
        if self._simulate:
            for start, end, _f in self._kept:
                seg_start_ms = start * 1000.0
                cur_ms = self._cap.get(cv2.CAP_PROP_POS_MSEC)
                if end > start and seg_start_ms - 30 <= cur_ms < end * 1000.0:
                    self._cap.set(cv2.CAP_PROP_POS_MSEC, end * 1000.0 + 1.0)
                    break
        ok, frame = self._cap.read()
        if not ok:
            self.pause()
            return
        self._show_frame(frame)
        self._src_time = self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        self._after_update()

    def _on_slider(self, value: int) -> None:
        self.set_time(value / 1000.0)

    def load(self, video_path) -> bool:
        self._cleanup_edited_audio()
        loaded = super().load(video_path)
        if loaded:
            self.slider.setRange(0, max(1, int(self._duration * 1000)))
            self._src_time = 0.0
            self._rebuild_mapping()
            self._rebuild_edited_audio()
        return loaded

    # -- composição -------------------------------------------------------

    def _show_frame(self, frame) -> None:
        frame = self._compose(frame)
        super()._show_frame(frame)

    def _compose(self, frame):
        t = self._src_time
        for ov in self._overlays:
            if ov["start"] <= t < ov["end"]:
                blended = self._overlay_frame(ov, t, frame)
                if blended is not None:
                    frame = _screen_blend(frame, blended)
        for img in self._images:
            if img["start"] <= t < img["end"]:
                frame = _paste_image(frame, img["path"])
        for co in self._callouts:
            if co["start"] <= t < co["end"]:
                frame = _draw_callout(frame, co["text"])
        return frame

    def _overlay_frame(self, ov, t, base_frame):
        import cv2

        key = str(ov["path"])
        cap = self._overlay_caps.get(key)
        if cap is None:
            cap = cv2.VideoCapture(key)
            if not cap.isOpened():
                self._overlay_caps[key] = False
                return None
            self._overlay_caps[key] = cap
        if cap is False:
            return None
        local_ms = max(0.0, (t - ov["start"])) * 1000.0
        # só refaz o seek se estiver longe do ponto atual (evita seek por tick)
        cur = cap.get(cv2.CAP_PROP_POS_MSEC)
        if abs(cur - local_ms) > 120.0:
            cap.set(cv2.CAP_PROP_POS_MSEC, local_ms)
        ok, oframe = cap.read()
        if not ok:
            return None
        return _resize_to(oframe, base_frame.shape)


# ----------------------------------------------------------------------
# Funções puras de composição (testáveis sem Qt)
# ----------------------------------------------------------------------


def _resize_to(frame, shape):
    import cv2

    h, w = shape[:2]
    return cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)


def _screen_blend(base, overlay):
    """Blend 'screen': fundos pretos do overlay somem (partículas, fumaça)."""
    import numpy as np

    b = base.astype(np.float32)
    o = overlay.astype(np.float32)
    out = 255.0 - (255.0 - b) * (255.0 - o) / 255.0
    return out.astype(base.dtype)


def _paste_image(frame, path):
    """Cola a imagem centrada com 85% da largura (destaque aprovado)."""
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return frame
    h, w = frame.shape[:2]
    target_w = int(w * 0.85)
    scale = target_w / img.shape[1]
    target_h = int(img.shape[0] * scale)
    img = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
    if img.shape[2] == 4:
        alpha = (img[:, :, 3].astype("float32") / 255.0)[:, :, None]
        rgb = img[:, :, :3].astype("float32")
    else:
        alpha = None
        rgb = img
    x = (w - target_w) // 2
    y = int(h * 0.12)
    y = min(y, max(0, h - target_h))
    region = frame[y : y + target_h, x : x + target_w]
    if alpha is not None:
        frame[y : y + target_h, x : x + target_w] = (
            rgb * alpha + region.astype("float32") * (1.0 - alpha)
        ).astype(frame.dtype)
    else:
        frame[y : y + target_h, x : x + target_w] = rgb
    return frame


def _draw_callout(frame, text):
    """Call-out amarelo grande no topo (aproximação do ASS \\an8)."""
    import cv2
    import numpy as np

    try:
        from PIL import Image, ImageDraw, ImageFont

        from config.settings import FONTS_DIR

        font_path = FONTS_DIR / "ArchivoBlack-Regular.ttf"
        h, w = frame.shape[:2]
        font = ImageFont.truetype(str(font_path), int(h * 0.06))
    except Exception:
        return frame

    text = " ".join(str(text).split())
    words = text.split()
    if len(words) > 6:
        text = " ".join(words[:6])
    text = text[:48].upper()

    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    # quebra em 2 linhas se estourar a largura
    max_w = int(w * 0.9)
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] > max_w and len(words) > 1:
        mid = len(words) // 2
        text = "\n".join([" ".join(words[:mid]), " ".join(words[mid:])])
    left, top = bbox[0], bbox[1]
    x = (w - min(bbox[2], max_w)) // 2
    y = int(h * 0.10)
    stroke = max(2, int(h * 0.004))
    draw.text(
        (x - left, y - top),
        text,
        font=font,
        fill=(255, 212, 0),
        stroke_width=stroke,
        stroke_fill=(0, 0, 0),
    )
    out = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return out


# ----------------------------------------------------------------------
# Prévia de áudio (ffplay embutido; cai no silêncio se indisponível)
# ----------------------------------------------------------------------

_audio_proc: subprocess.Popen | None = None


def play_audio_file(path) -> str | None:
    """Toca um arquivo de áudio sem bloquear a UI. Retorna erro ou None."""
    global _audio_proc
    stop_audio()
    from core.ffmpeg_path import _find_executable, subprocess_kwargs

    ffplay = _find_executable("ffplay")
    if ffplay is None:
        return "Nenhum player de áudio encontrado (ffplay ausente)."
    try:
        _audio_proc = subprocess.Popen(
            [
                str(ffplay),
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **subprocess_kwargs(),
        )
    except OSError as exc:
        return str(exc)
    return None


def stop_audio() -> None:
    global _audio_proc
    if _audio_proc is not None:
        try:
            _audio_proc.terminate()
        except OSError:
            pass
        _audio_proc = None
