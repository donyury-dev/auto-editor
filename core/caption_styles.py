"""Presets de estilo de legenda.

Ajuste cores, fontes e intensidade do destaque aqui — sem mexer na lógica
do motor de legendas. Para usar um preset, defina `caption_style` em
`config/app_settings.json` (campo `caption_style` das Settings).

Fontes embutidas em assets/fonts/ (Google Fonts, licença OFL):
- Anton             -> viral_amarelo (condensada, pesada, estilo CapCut)
- Archivo Black     -> impacto_vermelho (grotesca extra-bold)
- Poppins ExtraBold -> clean_ciano (arredondada, mais leve)

Cada preset é um `CaptionStyle`; adicionar um novo preset é criar uma
entrada nova neste dicionário.
"""

from __future__ import annotations

import logging

from core.subtitle_engine import CaptionStyle

logger = logging.getLogger(__name__)

PRESETS: dict[str, CaptionStyle] = {
    # Estilo clássico CapCut/Opus Clip: Anton, caixa alta, palavra ativa
    # amarela com pop/bounce até 135%.
    "viral_amarelo": CaptionStyle(
        font_name="Anton",
        font_size_vertical=74,
        font_size_horizontal=58,
        primary_color="#FFFFFF",
        highlight_color="#FFD400",
        outline=5,
        shadow=2,
        uppercase=True,
        active_scale=135,
        pop_animation=True,
        pop_overshoot=10,
        pop_duration_ms=140,
    ),
    # Impacto máximo: Archivo Black, contorno grosso, sombra forte,
    # destaque vermelho com bounce agressivo até 140%.
    "impacto_vermelho": CaptionStyle(
        font_name="Archivo Black",
        font_size_vertical=72,
        font_size_horizontal=56,
        primary_color="#FFFFFF",
        highlight_color="#FF3B30",
        outline=6,
        shadow=3,
        uppercase=True,
        active_scale=140,
        pop_animation=True,
        pop_overshoot=14,
        pop_duration_ms=160,
    ),
    # Mais sóbrio: Poppins ExtraBold, sem caixa alta, destaque ciano
    # sutil, sem animação de pop (zoom estático leve).
    "clean_ciano": CaptionStyle(
        font_name="Poppins ExtraBold",
        font_size_vertical=62,
        font_size_horizontal=50,
        primary_color="#FFFFFF",
        highlight_color="#00E5FF",
        outline=3,
        shadow=1,
        uppercase=False,
        active_scale=112,
        pop_animation=False,
    ),
}

DEFAULT_STYLE = "viral_amarelo"


def get_caption_style(name: str | None) -> CaptionStyle:
    """Retorna o preset pelo nome (ou o padrão, se desconhecido/vazio)."""
    if name and name in PRESETS:
        return PRESETS[name]
    if name:
        logger.warning(
            "Estilo de legenda desconhecido '%s'; usando '%s'.",
            name,
            DEFAULT_STYLE,
        )
    return PRESETS[DEFAULT_STYLE]
