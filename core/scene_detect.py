"""Detecção de mudança de cena (edição estilo anúncio).

Usa o filtro `select='gt(scene,T)'` + `showinfo` do FFmpeg para achar os
instantes em que o cenário muda. Os cortes de silêncio são então
alinhados a esses instantes: a edição acompanha o ritmo visual, não só
o ritmo da fala.

As funções puras (`parse_showinfo`, `align_cuts_to_scenes`) são testáveis
sem rodar FFmpeg.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from core.edit_plan import Cut
from core.ffmpeg_path import get_ffmpeg

logger = logging.getLogger(__name__)

# limiar padrão do filtro scene (0 = nada, 1 = tudo muda)
SCENE_THRESHOLD = 0.28
# tolerância p/ encaixar a borda de um corte numa mudança de cena
SCENE_SNAP_TOLERANCE_S = 0.4

_SHOWINFO_RE = re.compile(r"pts_time:([0-9]+\.?[0-9]*)")


def parse_showinfo(stderr_text: str) -> list[float]:
    """Extrai os pts_time das linhas showinfo do FFmpeg (pura)."""
    times = [float(m) for m in _SHOWINFO_RE.findall(stderr_text or "")]
    times.sort()
    # dedupe com tolerância mínima de 0.05s
    out: list[float] = []
    for t in times:
        if not out or t - out[-1] >= 0.05:
            out.append(t)
    return out


def detect_scene_changes(
    video_path: Path | str,
    threshold: float = SCENE_THRESHOLD,
    timeout_s: int = 600,
) -> list[float]:
    """Instantes (segundos) em que o cenário muda.

    Roda FFmpeg em resolução reduzida (só leitura de vídeo, sem saída).
    Em caso de falha, devolve lista vazia — a edição nunca deve travar
    por causa da detecção de cena.
    """
    cmd = [
        get_ffmpeg(),
        "-hide_banner",
        "-nostats",
        "-an",
        "-sn",
        "-i",
        str(video_path),
        "-vf",
        f"scale=384:-2,select='gt(scene,{threshold})',showinfo",
        "-fps_mode",
        "pass",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Detecção de cena falhou (%s); seguindo sem cenas.", exc)
        return []
    if proc.returncode != 0:
        logger.warning(
            "FFmpeg retornou %d na detecção de cena; seguindo sem cenas.",
            proc.returncode,
        )
        return []
    return parse_showinfo(proc.stderr)


def align_cuts_to_scenes(
    cuts: list[Cut],
    scene_times: list[float],
    tolerance: float = SCENE_SNAP_TOLERANCE_S,
) -> list[Cut]:
    """Encaixa as bordas dos cortes nas mudanças de cena próximas (pura).

    - borda a <= tolerância de uma cena → move para a cena
    - borda movida ganha "mudança de cenário" no motivo
    - cortes que colidem após o encaixe são mesclados
    Não muta os cortes de entrada.
    """
    if not cuts or not scene_times:
        return list(cuts)

    def nearest(t: float, lo: float | None = None, hi: float | None = None) -> float | None:
        best = None
        best_d = tolerance
        for s in scene_times:
            if lo is not None and s < lo:
                continue
            if hi is not None and s > hi:
                continue
            d = abs(s - t)
            if d < best_d:
                best = s
                best_d = d
        return best

    snapped: list[Cut] = []
    for c in cuts:
        start, end = c.start, c.end
        reasons = [c.reason] if c.reason else []
        ns = nearest(start, hi=end)
        if ns is not None and ns < end:
            start = ns
            reasons.append("mudança de cenário")
        ne = nearest(end, lo=start)
        if ne is not None and ne > start:
            end = ne
            reasons.append("mudança de cenário")
        if end <= start:
            continue
        snapped.append(
            Cut(
                start=start,
                end=end,
                reason=" · ".join(dict.fromkeys(reasons)),
                transition_type=c.transition_type,
                transition_duration=c.transition_duration,
            )
        )

    # mescla colisões criadas pelo encaixe
    merged: list[Cut] = []
    for c in sorted(snapped, key=lambda x: x.start):
        if merged and c.start < merged[-1].end:
            merged[-1].end = max(merged[-1].end, c.end)
            if c.reason and c.reason not in merged[-1].reason:
                merged[-1].reason = f"{merged[-1].reason} · {c.reason}"
        else:
            merged.append(c)
    return merged
