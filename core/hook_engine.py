"""Motor do gancho visual no início do vídeo.

Gera um arquivo ASS com um texto curto e impactante sobre os primeiros
segundos do vídeo, com efeitos animados (pulse, shake, zoom, bounce) e
controle de posição, cor e tamanho.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from core.edit_plan import HookBlock

logger = logging.getLogger(__name__)


@dataclass
class HookRenderSettings:
    """Configurações de renderização do gancho."""

    play_w: int = 1080
    play_h: int = 1920


def _hex_to_ass(hex_color: str) -> str:
    """Converte '#RRGGBB' para '&H00BBGGRR'."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b.upper()}{g.upper()}{r.upper()}"


def _fmt_time(seconds: float) -> str:
    """Formata segundos como 'h:mm:ss.cc' para ASS."""
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    hours, rem = divmod(cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _break_text(text: str, max_chars_per_line: int = 16) -> str:
    """Quebra o texto em linhas para caber na tela."""
    words = text.split()
    if not words:
        return ""
    lines: list[list[str]] = [[]]
    current_len = 0
    for word in words:
        wlen = len(word)
        if current_len + wlen + (1 if lines[-1] else 0) > max_chars_per_line and lines[-1]:
            lines.append([word])
            current_len = wlen
        else:
            lines[-1].append(word)
            current_len += wlen + (1 if len(lines[-1]) > 1 else 0)
    return "\\N".join(" ".join(line) for line in lines)


def _apply_effect(text: str, effect: str, duration: float) -> str:
    """Envolve o texto com tags ASS que criam o efeito escolhido."""
    if effect == "none" or not effect:
        return text

    if effect == "pulse":
        # Escala oscila suavemente entre 100% e 115% ao longo do tempo
        half = int((duration / 2) * 1000)
        return (
            f"{{\\t(0,{half},\\fscx115\\fscy115)}}"
            f"{{\\t({half},{int(duration*1000)},\\fscx100\\fscy100)}}"
            f"{text}"
        )

    if effect == "zoom":
        # Entra grande e assenta no tamanho final
        settle = min(400, int(duration * 1000 // 3))
        return (
            f"{{\\t(0,{settle},\\fscx40\\fscy40)}}"
            f"{{\\t({settle},{int(duration*1000)},\\fscx100\\fscy100)}}"
            f"{text}"
        )

    if effect == "bounce":
        # Overshoot: passa de 120% e volta para 100%
        peak = min(300, int(duration * 1000 // 4))
        return (
            f"{{\\t(0,{peak},\\fscx120\\fscy120)}}"
            f"{{\\t({peak},{int(duration*1000)},\\fscx100\\fscy100)}}"
            f"{text}"
        )

    if effect == "shake":
        # Tremor leve aplicado por keyframes
        steps = 8
        step_ms = int(duration * 1000 / steps)
        offsets = [(0, -3), (3, 0), (0, 3), (-3, 0), (0, -2), (2, 0), (0, 2), (-2, 0)]
        tags = ""
        for i, (dx, dy) in enumerate(offsets):
            t0 = i * step_ms
            t1 = (i + 1) * step_ms
            tags += f"{{\\t({t0},{t1},\\frx{dx}\\fry{dy})}}"
        return f"{tags}{text}"

    return text


def build_hook_ass(
    hook: HookBlock,
    out_path: Path,
    settings: HookRenderSettings | None = None,
) -> Path:
    """Gera o arquivo .ass do gancho a partir do HookBlock."""
    if not hook or not hook.enabled or not hook.text.strip():
        out_path.write_text("", encoding="utf-8")
        return out_path

    cfg = settings or HookRenderSettings()
    primary = _hex_to_ass(hook.color)
    highlight = _hex_to_ass(hook.highlight_color)

    # Tamanho base ajustado pela escala e pela resolução
    base_size = int(90 * hook.scale * (cfg.play_h / 1920))
    base_size = max(24, min(base_size, 260))
    outline = max(2, int(6 * hook.scale * (cfg.play_h / 1920)))
    shadow = max(1, int(3 * hook.scale * (cfg.play_h / 1920)))

    # Posição em pixels a partir das frações x, y
    pos_x = int(hook.x * cfg.play_w)
    pos_y = int(hook.y * cfg.play_h)

    text = hook.text.strip().upper()
    text = _break_text(text, max_chars_per_line=max(10, int(16 / max(hook.scale, 0.5))))
    text = _apply_effect(text, hook.effect, max(0.5, hook.end - hook.start))

    # \\\pos marca a posição absoluta do texto
    text = f"{{\\pos({pos_x},{pos_y})\\an5}}{text}"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {cfg.play_w}
PlayResY: {cfg.play_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{hook.font_family or 'Anton'},{base_size},{primary},{highlight},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    event = (
        f"Dialogue: 0,{_fmt_time(hook.start)},{_fmt_time(hook.end)},"
        f"Hook,,0,0,0,,{text}"
    )

    out_path.write_text(header + event + "\n", encoding="utf-8")
    return out_path
