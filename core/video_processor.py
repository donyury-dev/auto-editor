"""Motor de processamento de vídeo baseado em FFmpeg.

Responsável por: analisar o vídeo (ffprobe), queimar legendas ASS,
converter o formato (vertical 9:16 com fundo desfocado, horizontal 16:9
ou original) e reportar progresso de renderização.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from config.settings import (
    FONTS_DIR,
    HORIZONTAL_RESOLUTION,
    VERTICAL_RESOLUTION,
    OutputFormat,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


class VideoProcessingError(RuntimeError):
    """Erro durante execução do FFmpeg/ffprobe."""


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float

    @property
    def aspect_ratio(self) -> float:
        return self.width / max(1, self.height)


def resolve_target_resolution(
    fmt: OutputFormat, info: VideoInfo
) -> tuple[int, int]:
    """Retorna a resolução de saída para o formato escolhido."""
    if fmt == OutputFormat.VERTICAL:
        return VERTICAL_RESOLUTION
    if fmt == OutputFormat.HORIZONTAL:
        return HORIZONTAL_RESOLUTION
    return (info.width, info.height)


class VideoProcessor:
    """Wrapper do FFmpeg para renderização do vídeo final."""

    def probe(self, path: Path | str) -> VideoInfo:
        """Lê dimensões e duração do vídeo via ffprobe."""
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
        except FileNotFoundError as exc:
            raise VideoProcessingError(
                "ffprobe não encontrado. Instale o FFmpeg "
                "(https://ffmpeg.org) e certifique-se de que está no PATH."
            ) from exc
        if result.returncode != 0:
            raise VideoProcessingError(
                f"ffprobe falhou: {result.stderr.strip()[-400:]}"
            )
        data = json.loads(result.stdout)
        video = next(
            (
                s
                for s in data.get("streams", [])
                if s.get("codec_type") == "video"
            ),
            None,
        )
        if video is None:
            raise VideoProcessingError("Nenhuma faixa de vídeo encontrada.")
        duration = float(
            data.get("format", {}).get("duration")
            or video.get("duration")
            or 0.0
        )
        return VideoInfo(
            width=int(video["width"]), height=int(video["height"]), duration=duration
        )

    def _ass_filter_arg(self, ass_path: Path) -> str:
        arg = f"ass=filename='{ass_path.as_posix()}'"
        fonts = []
        if FONTS_DIR.exists():
            fonts = sorted(FONTS_DIR.glob("*.ttf")) + sorted(FONTS_DIR.glob("*.otf"))
        if fonts:
            arg += f":fontsdir='{FONTS_DIR.as_posix()}'"
        return arg

    def render(
        self,
        input_path: Path | str,
        ass_path: Path | str,
        output_path: Path | str,
        fmt: OutputFormat,
        progress: Optional[ProgressFn] = None,
    ) -> Path:
        """Renderiza o vídeo com legendas queimadas no formato escolhido."""
        input_path = Path(input_path)
        ass_path = Path(ass_path)
        output_path = Path(output_path)

        info = self.probe(input_path)
        target_w, target_h = resolve_target_resolution(fmt, info)
        ass_arg = self._ass_filter_arg(ass_path)

        if fmt == OutputFormat.ORIGINAL:
            # Apenas normaliza dimensões pares e queima as legendas.
            filter_args = [
                "-vf",
                f"scale=trunc(iw/2)*2:trunc(ih/2)*2,{ass_arg}",
            ]
        else:
            src_aspect = info.aspect_ratio
            target_aspect = target_w / target_h
            mismatch = (
                abs(src_aspect - target_aspect) / target_aspect > 0.05
            )
            if mismatch:
                # Fundo desfocado + vídeo centralizado (estilo Reels).
                filter_complex = (
                    "[0:v]split=2[bg][fg];"
                    f"[bg]scale={target_w}:{target_h}"
                    ":force_original_aspect_ratio=increase,"
                    f"crop={target_w}:{target_h},boxblur=20:2[bgb];"
                    f"[fg]scale={target_w}:{target_h}"
                    ":force_original_aspect_ratio=decrease[fgs];"
                    f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,{ass_arg}[v]"
                )
                filter_args = ["-filter_complex", filter_complex, "-map", "[v]"]
            else:
                filter_args = [
                    "-vf",
                    f"scale={target_w}:{target_h}"
                    f":force_original_aspect_ratio=increase,"
                    f"crop={target_w}:{target_h},{ass_arg}",
                ]

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            *filter_args,
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]
        logger.info("Renderizando: %s -> %s (%s)", input_path.name, output_path, fmt.value)

        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_file:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=err_file,
                    text=True,
                )
            except FileNotFoundError as exc:
                raise VideoProcessingError(
                    "ffmpeg não encontrado. Instale o FFmpeg "
                    "(https://ffmpeg.org) e certifique-se de que está no PATH."
                ) from exc

            duration = max(info.duration, 0.1)
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("out_time_ms=") or progress is None:
                    continue
                try:
                    elapsed_us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                frac = min(1.0, (elapsed_us / 1_000_000) / duration)
                progress(frac, f"renderizando… {int(frac * 100)}%")

            returncode = proc.wait()
            if returncode != 0:
                err_file.seek(0)
                err = err_file.read()
                raise VideoProcessingError(
                    f"FFmpeg falhou (código {returncode}): {err.strip()[-800:]}"
                )

        logger.info("Renderização concluída: %s", output_path)
        return output_path
