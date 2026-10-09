"""Palavras-chave atrás do apresentador (segmentação de pessoa).

Para cada trecho com palavra-chave, separa a pessoa do fundo quadro a
quadro (u2netp via onnxruntime, ~4.5 MB) e devolve PNGs RGBA só com a
pessoa. O pipeline renderiza o texto por cima do vídeo e depois
recoloca a pessoa na frente — o texto fica "atrás" dela, como nos
vídeos de referência.

Qualquer falha (modelo ausente, sem internet, onnxruntime quebrado)
faz o recurso cair no comportamento antigo (texto na frente), sem
quebrar o render.
"""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

MODEL_URL = (
    "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
)
_MASK_INPUT = 320
_MEAN = (0.485, 0.456, 0.406)
_STD = (0.229, 0.224, 0.225)
_FPS = 30.0  # extração e recolocação em 30 fps fixo
# Cobertura média da pessoa no quadro acima da qual a palavra fica na
# frente (close de webcam: overlay esconderia o texto por completo).
PERSON_COVER_MAX = 0.55


def model_path() -> Path:
    return PROJECT_ROOT / "models" / "mask" / "u2netp.onnx"


def ensure_model() -> Path:
    """Baixa o modelo de segmentação na primeira execução."""
    dest = model_path()
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Baixando modelo de máscara (u2netp, ~4.5 MB)…")
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    tmp.replace(dest)
    return dest


def merge_segments(
    segments: list[tuple[float, float]], pad: float = 0.15
) -> list[tuple[float, float]]:
    """Une segmentos próximos/sobrepostos (menos passes de máscara)."""
    if not segments:
        return []
    ordered = sorted((max(0.0, s - pad), e + pad) for s, e in segments)
    merged = [list(ordered[0])]
    for s, e in ordered[1:]:
        if s <= merged[-1][1] + 0.05:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


class PersonMasker:
    """Segmenta pessoa em frames (u2netp)."""

    def __init__(self, model_file: Path) -> None:
        import onnxruntime as ort

        self.session = ort.InferenceSession(
            str(model_file), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name

    def alpha(self, rgb) -> "object":
        """Máscara de pessoa (H×W, float 0..1) para um frame RGB."""
        import numpy as np
        from PIL import Image

        h, w = rgb.shape[:2]
        small = Image.fromarray(rgb).resize((_MASK_INPUT, _MASK_INPUT))
        x = np.asarray(small, dtype=np.float32) / 255.0
        x = (x - np.array(_MEAN, np.float32)) / np.array(_STD, np.float32)
        x = x.transpose(2, 0, 1)[None]
        pred = self.session.run(None, {self.input_name: x})[0][0, 0]
        lo, hi = float(pred.min()), float(pred.max())
        if hi - lo < 1e-6:
            return np.zeros((h, w), np.float32)
        pred = (pred - lo) / (hi - lo)
        img = Image.fromarray((pred * 255).astype("uint8")).resize((w, h))
        return np.asarray(img, np.float32) / 255.0


def person_overlay_segments(
    video_path,
    segments: list[tuple[float, float]],
    work_dir,
    ffmpeg_bin: str,
    progress=None,
) -> list[tuple[float, float, Path]] | None:
    """Gera PNGs RGBA (só a pessoa) para cada segmento do vídeo.

    Devolve [(start, end, pasta_dos_pngs)] ou None se o recurso não
    puder ser usado (modelo ausente/sem internet/erro de runtime).
    `progress(frac, msg)` reporta o andamento (0..1) para a barra.
    """
    import subprocess

    segs = merge_segments(segments)
    if not segs:
        return None
    # Limita o custo em CPU: no máximo 4 trechos, cada um com até 12s.
    segs = sorted(segs, key=lambda s: s[1] - s[0], reverse=True)[:4]
    segs = sorted(segs)
    try:
        model_file = ensure_model()
        masker = PersonMasker(model_file)
    except Exception as exc:
        logger.warning("Máscara de pessoa indisponível (%s); texto na frente.", exc)
        return None

    import numpy as np
    from PIL import Image

    work_dir = Path(work_dir)
    results: list[tuple[float, float, Path]] = []
    total_duration = sum(e - s for s, e in segs)
    fps = min(30.0, max(10.0, 420.0 / max(0.1, total_duration)))
    done_duration = 0.0

    def report(msg: str) -> None:
        if progress:
            progress(done_duration / max(0.1, total_duration), msg)

    try:
        for i, (s, e) in enumerate(segs):
            frames_dir = work_dir / f"mask{i}"
            person_dir = work_dir / f"person{i}"
            frames_dir.mkdir(parents=True, exist_ok=True)
            person_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-loglevel", "error",
                    "-ss", f"{max(0.0, s):.3f}", "-to", f"{e:.3f}",
                    "-i", str(video_path),
                    "-vf", f"fps={fps:g}",
                    str(frames_dir / "f_%05d.png"),
                ],
                check=True, capture_output=True,
            )
            frames = sorted(frames_dir.glob("f_*.png"))
            if not frames:
                done_duration += e - s
                report(f"trecho {i + 1}/{len(segs)} vazio")
                continue
            prev_alpha = None
            seg_alpha_mean = None
            for j, fp in enumerate(frames, start=1):
                img = Image.open(fp).convert("RGB")
                # Reuso temporal: a pessoa se move pouco entre quadros
                # vizinhos; a máscara só é recalculada a cada 2 quadros
                # (metade do custo de CPU, mesma qualidade visual).
                if prev_alpha is None or j % 2 == 1:
                    a = masker.alpha(np.asarray(img))
                    prev_alpha = a
                else:
                    a = prev_alpha
                if seg_alpha_mean is None:
                    seg_alpha_mean = float(a.mean())
                rgba = img.convert("RGBA")
                rgba.putalpha(Image.fromarray((a * 255).astype("uint8")))
                rgba.save(person_dir / f"person_{j:05d}.png")
                if j % 10 == 0:
                    report(
                        f"separando você do fundo (trecho {i + 1}/{len(segs)}, "
                        f"quadro {j}/{len(frames)})…"
                    )
            # Close de webcam: a pessoa cobre o quadro quase inteiro e o
            # overlay a recolocando por cima ESCONDE a palavra. Nesse caso
            # o texto fica NA FRENTE (como no vídeo modelo, onde a palavra
            # aparece sobre o corpo do apresentador) — trecho descartado.
            if seg_alpha_mean is not None and seg_alpha_mean > PERSON_COVER_MAX:
                logger.info(
                    "Pessoa cobre %.0f%% do quadro no trecho %.1fs; "
                    "palavra na frente.",
                    seg_alpha_mean * 100, s,
                )
                done_duration += e - s
                report(f"trecho {i + 1}/{len(segs)}: palavra na frente")
                continue
            results.append((s, e, person_dir))
            done_duration += e - s
            report(f"trecho {i + 1}/{len(segs)} separado")
    except Exception as exc:
        logger.warning("Falha ao segmentar pessoa (%s); texto na frente.", exc)
        return None
    return results or None


def overlay_person_segments(
    video_in,
    segs: list[tuple[float, float, Path]],
    video_out,
    ffmpeg_bin: str,
) -> None:
    """Recoloca a pessoa (PNGs RGBA) na frente do vídeo com texto."""
    import subprocess

    inputs: list[str] = ["-i", str(video_in)]
    chains: list[str] = []
    current = "0:v"
    for i, (s, e, person_dir) in enumerate(segs):
        idx = i + 1
        inputs += [
            "-framerate", f"{_FPS:g}", "-i", str(person_dir / "person_%05d.png"),
        ]
        chains.append(
            f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS+{s:.3f}/TB[p{i}]"
        )
        out = f"o{i}"
        chains.append(
            f"[{current}][p{i}]overlay=0:0:eof_action=pass:"
            f"enable='between(t,{s:.3f},{e:.3f})'[{out}]"
        )
        current = out
    cmd = [
        ffmpeg_bin, "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chains) + f";[{current}]null[out]",
        "-map", "[out]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "copy", str(video_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg (máscara) falhou: {proc.stderr[-800:]}")
