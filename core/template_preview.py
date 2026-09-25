"""Geração de preview estático para templates de estilo.

Cria uma imagem exemplo (frame 1080x1920) mostrando como a legenda e o
call-out de um template ficariam no vídeo final — sem precisar rodar o
pipeline completo.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.callout_engine import _clean_text
from core.subtitle_engine import rgb_to_ass
from core.templates import Template

logger = logging.getLogger(__name__)


# Margem horizontal mínima (em px) entre o texto e a borda do frame.
HORIZONTAL_MARGIN = 80


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _find_font(size: int, preferred: str = "Anton") -> ImageFont.FreeTypeFont:
    candidates = [
        Path("assets/fonts") / f"{preferred.replace(' ', '')}-Regular.ttf",
        Path("assets/fonts") / "Anton-Regular.ttf",
        Path("assets/fonts") / "ArchivoBlack-Regular.ttf",
        Path("assets/fonts") / "Poppins-ExtraBold.ttf",
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.Draw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _fit_text_lines(
    draw: ImageDraw.Draw,
    text: str,
    font_name: str,
    base_size: int,
    max_width: int,
    max_lines: int = 2,
    min_size: int = 36,
) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """Quebra o texto em linhas e, se necessário, reduz a fonte.

    Retorna as linhas e a fonte final que fazem o texto caber em
    `max_width` com no máximo `max_lines` linhas.
    """
    words = text.split()
    if not words:
        return [""], _find_font(base_size, font_name)

    size = base_size
    while size >= min_size:
        font = _find_font(size, font_name)
        # Tenta encaixar em até max_lines linhas usando word-wrap guloso.
        lines: list[str] = []
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if _text_width(draw, trial, font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
                if len(lines) >= max_lines:
                    # Estourou o número de linhas; diminui a fonte e tenta
                    # novamente.
                    break
        else:
            if current:
                lines.append(current)
            # Sucesso se cabe na largura e no número de linhas.
            if len(lines) <= max_lines and all(
                _text_width(draw, line, font) <= max_width for line in lines
            ):
                return lines, font
        size = int(size * 0.9)

    # Fallback: força quebra e usa a menor fonte testada.
    font = _find_font(min_size, font_name)
    lines = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _text_width(draw, trial, font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:max_lines] or [text[:20]], font


def _draw_outlined_text(
    draw: ImageDraw.Draw,
    xy: tuple[int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    outline: int,
) -> None:
    """Desenha texto com contorno, alinhado à esquerda a partir de xy."""
    x, y = xy
    line_spacing = int(font.size * 1.15)
    for line in lines:
        for dx in range(-outline, outline + 1, max(1, outline // 3)):
            for dy in range(-outline, outline + 1, max(1, outline // 3)):
                draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=fill)
        y += line_spacing


def generate_template_preview(
    template: Template,
    out_path: Path,
    width: int = 1080,
    height: int = 1920,
    sample_text: str = "CONTEÚDO VIRAL",
    sample_callout: str = "DESTAQUE",
) -> Path:
    """Renderiza uma imagem exemplo do template."""
    out_path = Path(out_path)
    img = Image.new("RGB", (width, height), color=(20, 20, 25))
    draw = ImageDraw.Draw(img)

    # Faixa de "vídeo" no centro (cinza escuro)
    video_margin = int(height * 0.12)
    draw.rectangle(
        [0, video_margin, width, height - video_margin],
        fill=(40, 40, 45),
    )

    # Silhueta de "pessoa" no centro (círculo + ombros)
    cx, cy = width // 2, height // 2
    r = min(width, height) // 8
    draw.ellipse([cx - r, cy - r * 2, cx + r, cy - r], fill=(90, 90, 95))
    draw.ellipse(
        [cx - r * 2, cy + r // 2, cx + r * 2, cy + r * 2],
        fill=(80, 80, 85),
    )

    max_text_width = width - 2 * HORIZONTAL_MARGIN

    # Call-out no topo
    callout_text = _clean_text(sample_callout).upper()
    callout_lines, callout_font = _fit_text_lines(
        draw, callout_text, template.callout_font_name, 120, max_text_width
    )
    callout_y = int(height * 0.18)
    # Centraliza o bloco de texto
    total_callout_w = max(
        _text_width(draw, line, callout_font) for line in callout_lines
    )
    callout_x = (width - total_callout_w) // 2
    _draw_outlined_text(
        draw,
        (callout_x, callout_y),
        callout_lines,
        callout_font,
        _hex_to_rgb(template.callout_color),
        outline=max(4, template.outline + 2),
    )

    # Legenda na parte inferior
    caption_text = _clean_text(sample_text).upper() if template.uppercase else _clean_text(sample_text)
    caption_lines, caption_font = _fit_text_lines(
        draw, caption_text, template.font_name, 90, max_text_width
    )
    caption_block_h = int(caption_font.size * 1.15 * len(caption_lines))
    caption_y = height - int(height * template.caption_vertical_position / 100) - caption_block_h
    total_caption_w = max(
        _text_width(draw, line, caption_font) for line in caption_lines
    )
    caption_x = (width - total_caption_w) // 2
    _draw_outlined_text(
        draw,
        (caption_x, caption_y),
        caption_lines,
        caption_font,
        _hex_to_rgb(template.highlight_color),
        outline=template.outline,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    logger.info("Preview do template salvo em %s", out_path)
    return out_path
