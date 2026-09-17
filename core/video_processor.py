"""Motor de processamento de vídeo baseado em FFmpeg.

Responsável por: analisar o vídeo (ffprobe), queimar legendas ASS,
converter o formato (vertical 9:16 com fundo desfocado, horizontal 16:9
ou original), aplicar o plano de edição (cortes, zooms, transições)
e reportar progresso de renderização.
"""

from __future__ import annotations

import json
import logging
import shutil
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
from core.edit_plan import EditPlan, ZOOM_RAMP_S

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


class VideoProcessingError(RuntimeError):
    """Erro durante execução do FFmpeg/ffprobe."""


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: float
    has_audio: bool = True

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
        has_audio = any(
            s.get("codec_type") == "audio" for s in data.get("streams", [])
        )
        return VideoInfo(
            width=int(video["width"]),
            height=int(video["height"]),
            duration=duration,
            has_audio=has_audio,
        )

    def _ass_filter_arg(self, ass_path: Path) -> str:
        arg = f"ass=filename='{ass_path.as_posix()}'"
        fonts = []
        if FONTS_DIR.exists():
            fonts = sorted(FONTS_DIR.glob("*.ttf")) + sorted(FONTS_DIR.glob("*.otf"))
        if fonts:
            arg += f":fontsdir='{FONTS_DIR.as_posix()}'"
        return arg

    def _build_filter_args(
        self, fmt: OutputFormat, info: VideoInfo, ass_arg: str
    ) -> list[str]:
        """Monta os argumentos de filtro e mapeamento de streams do ffmpeg.

        Importante: o vídeo é sempre mapeado explicitamente. Com qualquer
        `-map` presente, o ffmpeg desativa a seleção automática de streams —
        sem o mapa explícito, a saída sairia sem faixa de vídeo.
        """
        if fmt == OutputFormat.ORIGINAL:
            # Apenas normaliza dimensões pares e queima as legendas.
            return [
                "-vf",
                f"scale=trunc(iw/2)*2:trunc(ih/2)*2,{ass_arg}",
                "-map",
                "0:v:0",
            ]

        target_w, target_h = resolve_target_resolution(fmt, info)
        src_aspect = info.aspect_ratio
        target_aspect = target_w / target_h
        mismatch = abs(src_aspect - target_aspect) / target_aspect > 0.05
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
            return ["-filter_complex", filter_complex, "-map", "[v]"]
        return [
            "-vf",
            f"scale={target_w}:{target_h}"
            f":force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},{ass_arg}",
            "-map",
            "0:v:0",
        ]

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
        filter_args = self._build_filter_args(fmt, info, ass_arg)

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

        # Validação defensiva: o resultado precisa ter faixa de vídeo com as
        # dimensões esperadas (evita export silencioso sem vídeo).
        expected = (target_w - target_w % 2, target_h - target_h % 2)
        out_info = self.probe(output_path)
        if (out_info.width, out_info.height) != expected:
            raise VideoProcessingError(
                f"Saída inválida: esperado {expected[0]}x{expected[1]}, "
                f"obtido {out_info.width}x{out_info.height} "
                "(o ffmpeg pode ter descartado a faixa de vídeo)."
            )

        logger.info("Renderização concluída: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Fase 2: plano de edição (cortes + zooms + transições)
    # ------------------------------------------------------------------

    def _base_canvas_filter(self, fmt: OutputFormat, info: VideoInfo) -> str:
        """Filtro que converte o frame para o formato alvo (sem legendas)."""
        if fmt == OutputFormat.ORIGINAL:
            return "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        target_w, target_h = resolve_target_resolution(fmt, info)
        mismatch = (
            abs(info.aspect_ratio - target_w / target_h)
            / (target_w / target_h)
            > 0.05
        )
        if mismatch:
            return (
                "split=2[bg][fg];"
                f"[bg]scale={target_w}:{target_h}"
                ":force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h},boxblur=20:2[bgb];"
                f"[fg]scale={target_w}:{target_h}"
                ":force_original_aspect_ratio=decrease[fgs];"
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
            )
        return (
            f"scale={target_w}:{target_h}"
            f":force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}"
        )

    @staticmethod
    def _zoom_expression(
        local_zooms: list[tuple[float, float, float]]
    ) -> str:
        """Expressão do fator de zoom em função de t (local ao segmento).

        Cada zoom: rampa de entrada (RAMP_S), espera e rampa de saída.
        O fator total é o produto dos zooms (não devem sobrepor).
        """
        factor = "1"
        for ts, te, intensity in local_zooms:
            ramp = ZOOM_RAMP_S
            factor += (
                f"*(1+{intensity:.3f}"
                f"*clip((t-{ts:.3f})/{ramp},0,1)"
                f"*clip(({te:.3f}+{ramp}-t)/{ramp},0,1))"
            )
        return factor

    def _render_segment(
        self,
        input_path: Path,
        seg_start: float,
        seg_end: float,
        zooms: list,
        fmt: OutputFormat,
        info: VideoInfo,
        out_path: Path,
    ) -> None:
        """Renderiza um segmento mantido (com zooms que o intersectam)."""
        target_w, target_h = resolve_target_resolution(
            fmt, info
        )
        base = self._base_canvas_filter(fmt, info)
        local_zooms = [
            (
                max(z.start, seg_start) - seg_start,
                min(z.end, seg_end) - seg_start,
                z.intensity,
            )
            for z in zooms
            if z.start < seg_end and z.end > seg_start
        ]
        if local_zooms:
            f = self._zoom_expression(local_zooms)
            zoom_chain = (
                f",scale=w='{target_w}*{f}':h='{target_h}*{f}'"
                ":eval=frame:flags=lanczos"
                f",crop={target_w}:{target_h}:(iw-ow)/2:(ih-oh)/2"
            )
        else:
            zoom_chain = ""

        # filter_complex (não -vf) porque o canvas split/overlay usa labels
        fc = f"[0:v]{base}{zoom_chain}[vout]"

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{seg_start:.3f}", "-i", str(input_path),
            "-t", f"{max(0.05, seg_end - seg_start):.3f}",
            "-filter_complex", fc,
            "-map", "[vout]",
        ]
        if info.has_audio:
            cmd += ["-map", "0:a:0?"]
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        self._run_ffmpeg(cmd, f"segmento {seg_start:.1f}-{seg_end:.1f}s")

    def _run_ffmpeg(self, cmd: list[str], label: str) -> None:
        """Executa um comando ffmpeg capturando erros de forma legível."""
        logger.debug("ffmpeg [%s]: %s", label, " ".join(cmd))
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_file:
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=err_file, text=True
                )
            except FileNotFoundError as exc:
                if exc.filename and Path(exc.filename).name not in (
                    "ffmpeg",
                    "ffprobe",
                ):
                    # argumento inválido, não binário ausente
                    raise VideoProcessingError(
                        f"Comando FFmpeg malformado em '{label}': {exc}"
                    ) from exc
                raise VideoProcessingError(
                    "ffmpeg não encontrado. Instale o FFmpeg e garanta que "
                    "esteja no PATH."
                ) from exc
            returncode = proc.wait()
            if returncode != 0:
                err_file.seek(0)
                err = err_file.read()
                raise VideoProcessingError(
                    f"FFmpeg falhou em '{label}' (código {returncode}): "
                    f"{err.strip()[-600:]}"
                )

    def _join_segments(
        self, seg_paths: list[Path], plan: EditPlan, out_path: Path
    ) -> None:
        """Une os segmentos com transições (xfade) ou concat simples."""
        durations = [self.probe(p).duration for p in seg_paths]
        has_audio = self.probe(seg_paths[0]).has_audio
        td = min(plan.transition_duration, max(0.1, min(durations) * 0.4))
        n = len(seg_paths)

        inputs: list[str] = []
        for p in seg_paths:
            inputs += ["-i", str(p)]

        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs]

        if plan.transition_type == "corte":
            # corte seco: concat simples
            vstreams = "".join(f"[{i}:v:0]" for i in range(n))
            if has_audio:
                astreams = "".join(f"[{i}:a:0]" for i in range(n))
                fc = f"{vstreams}{astreams}concat=n={n}:v=1:a=1[v][a]"
                maps = ["-map", "[v]", "-map", "[a]"]
            else:
                fc = f"{vstreams}concat=n={n}:v=1[v]"
                maps = ["-map", "[v]"]
        else:
            # cadeia de xfade (vídeo) + acrossfade (áudio)
            parts: list[str] = []
            prev_v = "[0:v]"
            acc = durations[0]
            for i in range(1, n):
                out_v = f"[xv{i}]" if i < n - 1 else "[v]"
                offset = max(0.0, acc - td)
                parts.append(
                    f"{prev_v}[{i}:v]xfade=transition="
                    f"{plan.transition_type}"
                    f":duration={td:.3f}:offset={offset:.3f}{out_v}"
                )
                prev_v = out_v
                acc = acc + durations[i] - td
            if has_audio:
                prev_a = "[0:a]"
                for i in range(1, n):
                    out_a = f"[xa{i}]" if i < n - 1 else "[a]"
                    parts.append(
                        f"{prev_a}[{i}:a]acrossfade=d={td:.3f}{out_a}"
                    )
                    prev_a = out_a
                maps = ["-map", "[v]", "-map", "[a]"]
            else:
                maps = ["-map", "[v]"]
            fc = ";".join(parts)

        cmd += ["-filter_complex", fc, *maps]
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(out_path),
        ]
        self._run_ffmpeg(cmd, "junção de segmentos")

    def apply_edit_plan(
        self,
        input_path: Path | str,
        plan: EditPlan,
        info: VideoInfo,
        fmt: OutputFormat,
        output_path: Path | str,
        progress: Optional[ProgressFn] = None,
    ) -> Path:
        """Aplica cortes, zooms e transições do plano aprovado."""
        input_path = Path(input_path)
        output_path = Path(output_path)
        segments = plan.kept_segments()
        if not segments:
            raise VideoProcessingError(
                "Plano de edição remove todo o vídeo — nada a renderizar."
            )

        logger.info(
            "Aplicando plano: %d corte(s), %d zoom(s), %d segmento(s)",
            len(plan.cuts), len(plan.zooms), len(segments),
        )
        seg_dir = output_path.parent / "segs"
        seg_dir.mkdir(parents=True, exist_ok=True)

        total = sum(e - s for s, e in segments)
        done = 0.0
        seg_paths: list[Path] = []
        for i, (s, e) in enumerate(segments):
            seg_out = seg_dir / f"seg_{i:03d}.mp4"
            self._render_segment(
                input_path, s, e, plan.zooms, fmt, info, seg_out
            )
            seg_paths.append(seg_out)
            done += e - s
            if progress:
                progress(
                    0.7 * done / total,
                    f"segmento {i + 1}/{len(segments)} renderizado",
                )

        if len(seg_paths) == 1:
            shutil.move(str(seg_paths[0]), str(output_path))
        else:
            self._join_segments(seg_paths, plan, output_path)
        if progress:
            progress(1.0, "edição concluída")
        logger.info("Plano aplicado: %s", output_path)
        return output_path
