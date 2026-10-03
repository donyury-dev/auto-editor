"""Geração de uma camada ASS separada para call-outs de texto."""

from __future__ import annotations

import logging
from pathlib import Path

from core.illustration_plan import IllustrationMoment
from core.subtitle_engine import rgb_to_ass

logger = logging.getLogger(__name__)


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    centiseconds = int(round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _clean_text(text: str) -> str:
    return " ".join(
        text.replace("{", "").replace("}", "").replace("\n", " ").split()
    )


_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Callout,{font_name},{font_size},{primary},&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,8,4,8,100,100,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _short_text(moment: IllustrationMoment) -> str:
    text = _clean_text(
        moment.callout_text.strip()
        or moment.text.strip()
        or moment.prompt.strip()
    )
    words = text.split()
    if len(words) > 5:
        text = " ".join(words[:5])
    text = text[:40]
    # Quebra em duas linhas se for longo, para não ultrapassar a tela.
    if len(text) > 20:
        mid = len(text) // 2
        space = text.rfind(" ", 0, mid)
        if space == -1:
            space = text.find(" ", mid)
        if space != -1:
            text = text[:space] + "\\N" + text[space + 1 :]
    return text


def write_callouts_ass(
    moments: list[IllustrationMoment],
    out_path: Path,
    play_w: int,
    play_h: int,
) -> Path:
    """Escreve call-outs grandes, animados e separados das legendas."""
    vertical = play_h >= play_w
    # Ajusta fonte conforme texto: textos longos precisam de fonte menor
    # para não estourar a largura em 1080px (vertical).
    longest = max((len(_short_text(m).replace("\\N", " ")) for m in moments), default=0)
    if vertical:
        font_size = 84 if longest > 22 else 100
    else:
        font_size = 72 if longest > 22 else 84
    margin_v = int(play_h * (0.16 if vertical else 0.12))
    header = _HEADER.format(
        play_w=play_w,
        play_h=play_h,
        font_name="Archivo Black",
        font_size=font_size,
        primary=rgb_to_ass("#FFD400"),
        margin_v=margin_v,
    )

    lines = [header]
    count = 0
    for moment in moments:
        text = _short_text(moment)
        if not text or moment.end <= moment.start:
            continue
        start = _fmt_time(moment.start)
        end = _fmt_time(max(moment.end, moment.start + 0.05))
        lines.append(
            f"Dialogue: 20,{start},{end},Callout,,0,0,0,,"
            f"{{\\an8\\c{rgb_to_ass('#FFD400')}\\3c&H00000000"
            f"\\bord6\\shad4\\fad(120,220)\\fscx55\\fscy55"
            f"\\t(0,220,\\fscx115\\fscy115)"
            f"\\t(220,400,\\fscx105\\fscy105)"
            f"\\t(400,560,\\fscx100\\fscy100)}}"
            f"{text.upper()}{{\\r}}"
        )
        count += 1

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Call-outs gerados: %s (%d eventos)", out_path, count)
    return out_path