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
Style: Callout,{font_name},{font_size},{primary},&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,8,4,8,70,70,{margin_v},1

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
    if len(words) > 6:
        text = " ".join(words[:6])
    return text[:48]


def write_callouts_ass(
    moments: list[IllustrationMoment],
    out_path: Path,
    play_w: int,
    play_h: int,
) -> Path:
    """Escreve call-outs grandes, animados e separados das legendas."""
    vertical = play_h >= play_w
    font_size = 116 if vertical else 84
    margin_v = int(play_h * (0.14 if vertical else 0.12))
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
            f"\\bord8\\shad4\\fad(80,220)\\fscx55\\fscy55\\frz-6"
            f"\\t(0,180,\\fscx130\\fscy130\\frz5)"
            f"\\t(180,360,\\fscx110\\fscy110\\frz-2)"
            f"\\t(360,520,\\fscx100\\fscy100\\frz0)}}"
            f"{text.upper()}{{\\r}}"
        )
        count += 1

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Call-outs gerados: %s (%d eventos)", out_path, count)
    return out_path