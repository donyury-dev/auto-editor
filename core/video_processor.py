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
    _detect_ram_gb,
)
from core.edit_plan import EditPlan
from core.face_detection import detect_face_center
from core.ffmpeg_path import get_ffmpeg, get_ffprobe, subprocess_kwargs

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]

# Centro padrão do crop quando nenhum rosto é detectado. Usamos o centro
# real do frame (0.5, 0.5): valores mais altos/baixos geram coordenadas de
# crop negativas que o FFmpeg clampa, anulando o efeito do centro.
FACE_FALLBACK_CX = 0.5
FACE_FALLBACK_CY = 0.5


def low_ram_mode() -> bool:
    """True em servidores com pouca memória (ex.: Render 512 MB).

    No modo leve o render abre mão dos efeitos mais pesados (zoom por
    quadro, cadeia de xfade com N entradas simultâneas, overlays de
    imagem) e usa encoder econômico — a prioridade é COMPLETAR o vídeo
    com bons cortes e boa legenda.
    """
    return 0 < _detect_ram_gb() < 1.5


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
            get_ffprobe(),
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
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                **subprocess_kwargs(),
            )
        except FileNotFoundError as exc:
            raise VideoProcessingError(
                "ffprobe não encontrado. O pacote deve incluir o FFmpeg "
                "em bin/ffmpeg/ ou o FFmpeg deve estar no PATH."
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

    @staticmethod
    def _escape_filter_path(path: Path) -> str:
        """Escapa um caminho para uso dentro de um filtro ffmpeg.

        No Windows, o ':' da letra do drive (ex.: C:/Users/...) é
        interpretado como separador de opções do filtro e quebra o
        parser do filtergraph ('No option name near...'). Escapar como
        'C\\:/Users/...' (padrão recomendado pela documentação do
        ffmpeg para os filtros ass/subtitles).
        """
        return path.as_posix().replace(":", r"\:")

    def _ass_filter_arg(self, ass_path: Path) -> str:
        ass = self._escape_filter_path(ass_path)
        arg = f"ass=filename='{ass}'"
        fonts = []
        if FONTS_DIR.exists():
            fonts = sorted(FONTS_DIR.glob("*.ttf")) + sorted(FONTS_DIR.glob("*.otf"))
        if fonts:
            arg += f":fontsdir='{self._escape_filter_path(FONTS_DIR)}'"
        return arg

    def _build_filter_args(
        self,
        fmt: OutputFormat,
        info: VideoInfo,
        ass_arg: str,
        lut_file: str | None = None,
    ) -> list[str]:
        """Monta os argumentos de filtro e mapeamento de streams do ffmpeg.

        `lut_file` (já escapado) aplica color grading ANTES das legendas.

        Importante: o vídeo é sempre mapeado explicitamente. Com qualquer
        `-map` presente, o ffmpeg desativa a seleção automática de streams —
        sem o mapa explícito, a saída sairia sem faixa de vídeo.
        """
        lut = f"lut3d=file='{lut_file}'," if lut_file else ""
        if fmt == OutputFormat.ORIGINAL:
            # Apenas normaliza dimensões pares e queima as legendas.
            return [
                "-vf",
                f"{lut}scale=trunc(iw/2)*2:trunc(ih/2)*2,{ass_arg}",
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
                f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,{lut}{ass_arg}[v]"
            )
            return ["-filter_complex", filter_complex, "-map", "[v]"]
        return [
            "-vf",
            f"{lut}scale={target_w}:{target_h}"
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
        lut_path: Path | str | None = None,
    ) -> Path:
        """Renderiza o vídeo com legendas queimadas no formato escolhido.

        `lut_path` (opcional) aplica um LUT (.cube) do pack externo antes
        das legendas — a cor muda, o texto permanece legível.
        """
        input_path = Path(input_path)
        ass_path = Path(ass_path)
        output_path = Path(output_path)

        info = self.probe(input_path)
        target_w, target_h = resolve_target_resolution(fmt, info)
        ass_arg = self._ass_filter_arg(ass_path)
        lut_file = self._escape_filter_path(Path(lut_path)) if lut_path else None
        filter_args = self._build_filter_args(fmt, info, ass_arg, lut_file=lut_file)

        cmd = [
            get_ffmpeg(),
            "-y",
            "-i",
            str(input_path),
            *filter_args,
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast" if low_ram_mode() else "medium",
            "-crf",
            "22" if low_ram_mode() else "20",
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
                    **subprocess_kwargs(),
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
    def _zoom_expressions(
        local_zooms: list[tuple[float, float, float, float, float]]
    ) -> tuple[str, str, str]:
        """Expressões de zoom e centro do crop em função de t (local).

        Cada zoom: push-in suave (meia onda cosseno) + centro do crop
        detectado no rosto naquele momento. Quando nenhum zoom está ativo,
        o crop volta para o centro padrão (0.5, 0.5).
        """
        factor = "1"
        cx_expr = "0.5"
        cy_expr = "0.5"
        for ts, te, intensity, face_cx, face_cy in local_zooms:
            duration = max(0.001, te - ts)
            envelope = (
                f"(0.5-0.5*cos(PI*clip((t-{ts:.3f})/{duration:.3f},0,1)))"
            )
            factor += f"*(1+{intensity:.3f}*{envelope})"
            window = f"gte(t,{ts:.3f})*lte(t,{te:.3f})"
            cx_expr += f"+({face_cx:.3f}-0.5)*{window}"
            cy_expr += f"+({face_cy:.3f}-0.5)*{window}"
        return factor, cx_expr, cy_expr

    def _extract_frame(
        self, input_path: Path, timestamp: float, out_path: Path
    ) -> bool:
        """Extrai um único frame do vídeo no timestamp especificado."""
        cmd = [
            get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{timestamp:.3f}", "-i", str(input_path),
            "-frames:v", "1", "-q:v", "2",
            str(out_path),
        ]
        try:
            self._run_ffmpeg(cmd, f"frame em {timestamp:.2f}s")
            return out_path.exists() and out_path.stat().st_size > 0
        except VideoProcessingError:
            return False

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

        # Modo leve: zoom por quadro (scale eval=frame + lanczos) é um dos
        # pontos mais pesados do render — desliga em servidores pequenos.
        if low_ram_mode():
            zooms = []

        intersecting = [
            z for z in zooms if z.start < seg_end and z.end > seg_start
        ]

        local_zooms: list[tuple[float, float, float, float, float]] = []
        if intersecting:
            frame_dir = out_path.parent / "face_frames"
            frame_dir.mkdir(parents=True, exist_ok=True)

        for z in intersecting:
            ts = max(z.start, seg_start) - seg_start
            te = min(z.end, seg_end) - seg_start
            # detecta rosto em até 3 frames do zoom (início, meio, fim)
            source_ts_list = [
                max(z.start, seg_start) + 0.05,
                (max(z.start, seg_start) + min(z.end, seg_end)) / 2,
                min(z.end, seg_end) - 0.05,
            ]
            detections: list[tuple[float, float]] = []
            for idx, source_ts in enumerate(source_ts_list):
                frame_path = frame_dir / f"face_{z.start:.3f}_{idx}.jpg"
                if self._extract_frame(input_path, source_ts, frame_path):
                    detected = detect_face_center(frame_path)
                    if detected:
                        detections.append(detected)
            if detections:
                face_cx = sum(d[0] for d in detections) / len(detections)
                face_cy = sum(d[1] for d in detections) / len(detections)
                logger.info(
                    "Zoom em %.2f-%.2f: rosto em cx=%.3f cy=%.3f (%d detecções)",
                    z.start, z.end, face_cx, face_cy, len(detections),
                )
            else:
                face_cx, face_cy = FACE_FALLBACK_CX, FACE_FALLBACK_CY
                logger.warning(
                    "Zoom em %.2f-%.2f: nenhum rosto detectado; "
                    "usando centro padrão (%.2f, %.2f)",
                    z.start, z.end, face_cx, face_cy,
                )
            local_zooms.append((ts, te, z.intensity, face_cx, face_cy))

        if local_zooms:
            f, cx_expr, cy_expr = self._zoom_expressions(local_zooms)
            # Expressões com vírgulas precisam ficar entre aspas simples no
            # filter_complex; escape '\,' fora de aspas NÃO funciona nesta
            # build do FFmpeg (gte/lte avaliam para 0 constante). Os
            # parênteses em volta da expressão do centro são obrigatórios:
            # sem eles, o gate multiplica iw/ih e gera coordenadas sempre
            # negativas, que o FFmpeg clampa para 0 (centro nunca muda).
            zoom_chain = (
                f",scale=w='{target_w}*{f}':h='{target_h}*{f}'"
                ":eval=frame:flags=lanczos"
                f",crop={target_w}:{target_h}"
                f":'({cx_expr})*iw-ow/2':'({cy_expr})*ih-oh/2'"
            )
        else:
            zoom_chain = ""

        # filter_complex (não -vf) porque o canvas split/overlay usa labels
        fc = f"[0:v]{base}{zoom_chain}[vout]"

        cmd = [
            get_ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{seg_start:.3f}",
            "-i",
            str(input_path),
            "-t",
            f"{max(0.05, seg_end - seg_start):.3f}",
            "-filter_complex",
            fc,
            "-map",
            "[vout]",
        ]
        if info.has_audio:
            # Aplica fade in/out curto no áudio para evitar cliques nos cortes
            seg_dur = max(0.05, seg_end - seg_start)
            fade_d = min(0.03, seg_dur / 3)
            cmd += [
                "-filter_complex",
                f"[0:a:0]afade=t=in:st=0:d={fade_d},"
                f"afade=t=out:st={seg_dur - fade_d}:d={fade_d}[aout]",
                "-map",
                "[aout]",
            ]
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
        cmd = [str(c) for c in cmd]
        logger.debug("ffmpeg [%s]: %s", label, " ".join(cmd))
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_file:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=err_file,
                    text=True,
                    **subprocess_kwargs(),
                )
            except FileNotFoundError as exc:
                missing_name = Path(exc.filename).name if exc.filename else "ffmpeg"
                if missing_name not in ("ffmpeg", "ffprobe"):
                    # argumento inválido, não binário ausente
                    raise VideoProcessingError(
                        f"Comando FFmpeg malformado em '{label}': {exc}"
                    ) from exc
                raise VideoProcessingError(
                    "ffmpeg não encontrado. O pacote deve incluir o FFmpeg "
                    "em bin/ffmpeg/ ou o FFmpeg deve estar no PATH."
                ) from exc
            returncode = proc.wait()
            if returncode != 0:
                err_file.seek(0)
                err = err_file.read()
                raise VideoProcessingError(
                    f"FFmpeg falhou em '{label}' (código {returncode}): "
                    f"{err.strip()[-600:]}"
                )

    def _join_segments_concat_copy(
        self, seg_paths: list[Path], out_path: Path
    ) -> None:
        """Junção leve: concat demuxer + stream copy (um arquivo por vez).

        Se a cópia falhar (parâmetros divergentes entre segmentos), cai
        para re-encode único do concat demuxer (still leve: 1 entrada).
        """
        list_file = out_path.parent / "concat_list.txt"
        list_file.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in seg_paths),
            encoding="utf-8",
        )
        base_cmd = [
            get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
        ]
        copy_cmd = [
            *base_cmd,
            "-map", "0:v:0?", "-map", "0:a?",
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path),
        ]
        try:
            self._run_ffmpeg(copy_cmd, "junção leve (cópia direta)")
            return
        except VideoProcessingError:
            logger.warning(
                "Stream copy falhou na junção; re-encodando em modo leve."
            )
        reencode_cmd = [
            *base_cmd,
            "-map", "0:v:0?", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-threads", "2", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        self._run_ffmpeg(reencode_cmd, "junção leve (re-encode)")

    def _join_segments(
        self, seg_paths: list[Path], plan: EditPlan, out_path: Path
    ) -> None:
        """Despacho: modo leve → cópia direta; normal → xfade/concat."""
        if low_ram_mode():
            self._join_segments_concat_copy(seg_paths, out_path)
            return
        self._join_segments_full(seg_paths, plan, out_path)

    def _join_segments_full(
        self, seg_paths: list[Path], plan: EditPlan, out_path: Path
    ) -> None:
        """Une os segmentos com transições (xfade) ou concat simples.

        Cada junção usa a transição do corte que a gerou quando o corte
        define um override (`Cut.transition_type`); cortes sem override
        usam a transição global do plano.
        """
        durations = [self.probe(p).duration for p in seg_paths]
        has_audio = self.probe(seg_paths[0]).has_audio
        n = len(seg_paths)

        # transição efetiva por junção (junção i fica entre seg i-1 e i)
        join_types: list[str] = []
        join_durs: list[float] = []
        for i in range(n - 1):
            cut = plan.cuts[i] if i < len(plan.cuts) else None
            ttype = (
                cut.transition_type
                if cut is not None and cut.transition_type
                else plan.transition_type
            )
            tdur = (
                cut.transition_duration
                if cut is not None and cut.transition_duration
                else plan.transition_duration
            )
            join_types.append(ttype)
            join_durs.append(min(1.0, max(0.1, tdur)))

        inputs: list[str] = []
        for p in seg_paths:
            inputs += ["-i", str(p)]

        cmd = [get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *inputs]

        if all(t == "corte" for t in join_types):
            # corte seco em todas as junções: concat simples
            # (esta build exige vídeo/áudio alternados)
            if has_audio:
                streams = ""
                for i in range(n):
                    streams += f"[{i}:v:0][{i}:a:0]"
                fc = f"{streams}concat=n={n}:v=1:a=1[v][a]"
                maps = ["-map", "[v]", "-map", "[a]"]
            else:
                vstreams = "".join(f"[{i}:v:0]" for i in range(n))
                fc = f"{vstreams}concat=n={n}:v=1[v]"
                maps = ["-map", "[v]"]
        else:
            # cadeia de xfade (vídeo) + acrossfade (áudio), com a transição
            # de cada junção vinda do corte correspondente. Junções do tipo
            # "corte" usam um fade de 0.1s (lê-se como corte seco dentro
            # da cadeia de xfade).
            parts: list[str] = []
            for i in range(n):
                parts.append(f"[{i}:v]format=pix_fmts=yuv420p[v{i}]")
            prev_v = "[v0]"
            acc = durations[0]
            for i in range(1, n):
                out_v = f"[xv{i}]" if i < n - 1 else "[v]"
                d = join_durs[i - 1]
                ttype = join_types[i - 1]
                if ttype == "corte":
                    ttype = "fade"
                    d = 0.1
                offset = max(0.0, acc - d)
                parts.append(
                    f"{prev_v}[v{i}]xfade=transition="
                    f"{ttype}"
                    f":duration={d:.3f}:offset={offset:.3f}{out_v}"
                )
                prev_v = out_v
                acc = acc + durations[i] - d
            if has_audio:
                prev_a = "[0:a]"
                for i in range(1, n):
                    out_a = f"[xa{i}]" if i < n - 1 else "[a]"
                    d = 0.1 if join_types[i - 1] == "corte" else join_durs[i - 1]
                    parts.append(f"{prev_a}[{i}:a]acrossfade=d={d:.3f}{out_a}")
                    prev_a = out_a
                maps = ["-map", "[v]", "-map", "[a]"]
            else:
                maps = ["-map", "[v]"]
            fc = ";".join(parts)

        cmd += ["-filter_complex", fc, *maps]
        if low_ram_mode():
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-threads", "2", "-pix_fmt", "yuv420p",
            ]
        else:
            cmd += [
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuv420p",
            ]
        cmd += [
            "-c:a", "aac", "-b:a", "192k",
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

    # ------------------------------------------------------------------
    # Ilustrações (B-roll)
    # ------------------------------------------------------------------

    ILLUSTRATION_FADE_S = 0.4  # fade in/out da ilustração
    ILLUSTRATION_WIDTH_PCT = 0.85  # largura relativa à tela
    ILLUSTRATION_MAX_HEIGHT_PCT = 0.35  # altura máxima relativa à tela
    ILLUSTRATION_TOP_PCT = 12  # posição do topo (% da altura)

    def apply_callouts(
        self,
        input_path: Path | str,
        ass_path: Path | str,
        info: VideoInfo,
        fmt: OutputFormat,
        output_path: Path | str,
        progress: Optional[ProgressFn] = None,
    ) -> Path:
        """Queima a camada ASS de call-outs sem misturá-la às legendas."""
        input_path = Path(input_path)
        ass_path = Path(ass_path)
        output_path = Path(output_path)
        current_info = self.probe(input_path)
        target_w, target_h = resolve_target_resolution(fmt, current_info)
        filter_args = self._build_filter_args(
            fmt, current_info, self._ass_filter_arg(ass_path)
        )
        cmd = [
            get_ffmpeg(),
            "-y",
            "-i",
            str(input_path),
            *filter_args,
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
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
        logger.info("Aplicando call-outs: %s -> %s", input_path.name, output_path)
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err_file:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=err_file,
                    text=True,
                    **subprocess_kwargs(),
                )
            except FileNotFoundError as exc:
                raise VideoProcessingError(
                    "ffmpeg não encontrado. Instale o FFmpeg "
                    "e certifique-se de que está no PATH."
                ) from exc

            duration = max(current_info.duration, 0.1)
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
                progress(frac, f"call-outs… {int(frac * 100)}%")

            returncode = proc.wait()
            if returncode != 0:
                err_file.seek(0)
                err = err_file.read()
                raise VideoProcessingError(
                    f"FFmpeg falhou nos call-outs (código {returncode}): "
                    f"{err.strip()[-800:]}"
                )

        out_info = self.probe(output_path)
        expected = (target_w - target_w % 2, target_h - target_h % 2)
        if (out_info.width, out_info.height) != expected:
            raise VideoProcessingError(
                f"Saída de call-out inválida: esperado "
                f"{expected[0]}x{expected[1]}, obtido "
                f"{out_info.width}x{out_info.height}."
            )
        if progress:
            progress(1.0, "call-outs aplicados")
        return output_path

    @classmethod
    def _illustration_overlay_chain(
        cls,
        target_w: int,
        target_h: int,
        items: list[tuple[float, float, int]],
    ) -> tuple[list[str], list[str]]:
        """Monta a cadeia de filtros de overlay das ilustrações.

        `items`: (start, end, input_index) — timestamps na linha do tempo
        DO VÍDEO SENDO PROCESSADO. Retorna (filter_parts, map_labels):
        `filter_parts` são trechos de filter_complex (a montar com ';'),
        e `map_labels` os rótulos de entrada/saída para o chamador.
        """
        if not items:
            return [], []

        img_w = int(target_w * cls.ILLUSTRATION_WIDTH_PCT)
        img_h_max = int(target_h * cls.ILLUSTRATION_MAX_HEIGHT_PCT)
        fade = cls.ILLUSTRATION_FADE_S

        parts: list[str] = []
        inputs: list[str] = []
        prev = "[0:v]"
        for i, (start, end, idx) in enumerate(items):
            inputs += ["-loop", "1", "-t", f"{end:.3f}", "-i", f"__IMG{idx}__"]
            fade_out_st = max(0.0, end - fade)
            parts.append(
                f"[{idx}:v]scale={img_w}:{img_h_max}:"
                f"force_original_aspect_ratio=decrease,format=rgba,"
                f"fade=t=in:st={start:.3f}:d={fade}:alpha=1,"
                f"fade=t=out:st={fade_out_st:.3f}:d={fade}:alpha=1[il{i}]"
            )
            out = f"[ov{i}]"
            parts.append(
                f"{prev}[il{i}]overlay=x='(W-w)/2':"
                f"y='{cls.ILLUSTRATION_TOP_PCT}*H/100':"
                f"enable='between(t,{start:.3f},{end:.3f})'{out}"
            )
            prev = out
        return parts, inputs

    def apply_illustrations(
        self,
        input_path: Path | str,
        illustrations: list,
        info: VideoInfo,
        fmt: OutputFormat,
        output_path: Path | str,
        progress: Optional[ProgressFn] = None,
    ) -> Path:
        """Sobrepõe as ilustrações aprovadas ao vídeo.

        `illustrations`: list[IllustrationMoment] com timestamps JÁ
        remapeados para a linha do tempo do `input_path`. A imagem ocupa a
        faixa superior (acima da zona da legenda) com fade in/out — nunca
        cobre a legenda, que é queimada depois, por cima.
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        target_w, target_h = resolve_target_resolution(fmt, info)

        usable = [
            (m.start, m.end, Path(m.image_path))
            for m in illustrations
            if m.image_path and Path(m.image_path).exists()
        ]
        if not usable:
            logger.info("Nenhuma ilustração aplicável; pulando overlay.")
            if input_path != output_path:
                shutil.copyfile(input_path, output_path)
            return output_path

        # normaliza o canvas (o vídeo pode não ter passado pela edição)
        base = self._base_canvas_filter(fmt, info)
        items = [
            (s, e, i + 1) for i, (s, e, _p) in enumerate(usable)
        ]
        parts, input_args = self._illustration_overlay_chain(
            target_w, target_h, items
        )
        parts = [f"[0:v]{base}[vbase]"] + [
            p if not p.startswith("[0:v]") else p.replace("[0:v]", "[vbase]", 1)
            for p in parts
        ]
        # resolve os placeholders __IMGn__ para os caminhos reais
        resolved: list[str] = []
        for arg in input_args:
            if arg.startswith("__IMG") and arg.endswith("__"):
                idx = int(arg[5:-2])
                resolved.append(str(usable[idx - 1][2]))
            else:
                resolved.append(arg)

        cmd = [
            get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path), *resolved,
            "-filter_complex", ";".join(parts),
            "-map", "[ov{}]".format(len(items) - 1),
        ]
        if info.has_audio:
            cmd += ["-map", "0:a:0?"]
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(output_path),
        ]
        self._run_ffmpeg(cmd, f"{len(items)} ilustração(ões)")
        if progress:
            progress(1.0, f"{len(items)} ilustração(ões) aplicadas")
        logger.info("Ilustrações aplicadas: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Fase 7: overlays do pack externo (vídeos/imagens com fade)
    # ------------------------------------------------------------------

    # categorias cujos assets cobrem o frame inteiro (efeitos decorativos)
    FULLFRAME_CATEGORIES = {"overlays", "light_leaks", "backgrounds"}

    @staticmethod
    def build_overlay_chain(
        target_w: int,
        target_h: int,
        items: list[dict],
    ) -> tuple[list[str], list[str]]:
        """Monta o filter_complex de overlays (função pura, testável).

        `items`: [{"input": n, "start": s, "end": e, "full": bool}]
        onde `input` é o índice do input ffmpeg (1-based) do asset.

        Retorna (partes_do_filtro, args_de_input). Os inputs de imagem
        vêm com placeholder "__IMGn__" para o chamador adicionar -loop 1.
        """
        parts: list[str] = []
        input_args: list[str] = []
        prev = "[0:v]"
        fade_d = 0.25
        for i, item in enumerate(items):
            n = item["input"]
            start = max(0.0, float(item["start"]))
            end = max(start + 0.5, float(item["end"]))
            label = f"[ov{i}]"
            if item.get("full"):
                scale = (
                    f"scale={target_w}:{target_h}"
                    ":force_original_aspect_ratio=decrease,"
                    f"setsar=1"
                )
            else:
                scale = (
                    f"scale=-2:{int(target_h * 0.3)}"
                    ":force_original_aspect_ratio=decrease"
                )
            chain = (
                f"[{n}:v]{scale},format=rgba,"
                f"setpts=PTS+{start:.3f}/TB,"
                f"fade=t=in:st={start:.3f}:d={fade_d}:alpha=1,"
                f"fade=t=out:st={max(0.0, end - fade_d):.3f}:d={fade_d}:alpha=1"
                f"{label}"
            )
            parts.append(chain)
            x = "0" if item.get("full") else "(W-w)/2"
            y = "0" if item.get("full") else f"{int(target_h * 0.28)}"
            parts.append(
                f"{prev}{label}overlay={x}:{y}:"
                f"enable='between(t,{start:.3f},{end:.3f})'"
                f"[ovx{i}]"
            )
            prev = f"[ovx{i}]"
        return parts, input_args

    def apply_overlays(
        self,
        input_path: Path | str,
        overlays: list,
        info: VideoInfo,
        fmt: OutputFormat,
        output_path: Path | str,
        progress: Optional[ProgressFn] = None,
    ) -> Path:
        """Aplica overlays do pack externo (imagem ou vídeo) com fade.

        `overlays`: objetos com .path, .start, .end e .category —
        timestamps já na linha do tempo do `input_path`.
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        target_w, target_h = resolve_target_resolution(fmt, info)

        usable = [
            o for o in overlays if Path(o.path).exists()
        ]
        if not usable:
            if input_path != output_path:
                shutil.copyfile(input_path, output_path)
            if progress:
                progress(1.0, "nenhum overlay do pack a aplicar")
            return output_path

        base = self._base_canvas_filter(fmt, info)
        parts = [f"[0:v]{base}[vbase]"]
        cmd = [
            get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
        ]
        items = []
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
        input_idx = 1
        for o in usable:
            is_image = Path(o.path).suffix.lower() in image_exts
            if is_image:
                cmd += ["-loop", "1", "-i", str(o.path)]
            else:
                cmd += ["-i", str(o.path)]
            items.append(
                {
                    "input": input_idx,
                    "start": o.start,
                    "end": o.end,
                    "full": o.category in self.FULLFRAME_CATEGORIES,
                }
            )
            input_idx += 1

        chain_parts, _ = self.build_overlay_chain(target_w, target_h, items)
        # o primeiro overlay usa [vbase] como base
        if chain_parts:
            first = chain_parts[1]
            chain_parts[1] = first.replace("[0:v]", "[vbase]", 1)
        parts += chain_parts
        final_label = (
            f"[ovx{len(items) - 1}]" if items else "[vbase]"
        )

        cmd += [
            "-filter_complex", ";".join(parts),
            "-map", final_label,
        ]
        if info.has_audio:
            cmd += ["-map", "0:a:0?"]
        cmd += [
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(output_path),
        ]
        self._run_ffmpeg(cmd, f"{len(items)} overlay(s) do pack")
        if progress:
            progress(1.0, f"{len(items)} overlay(s) do pack aplicados")
        logger.info("Overlays do pack aplicados: %s", output_path)
        return output_path
