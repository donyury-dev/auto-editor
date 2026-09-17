"""Presets de estilo de legenda.

Ajuste cores, fontes e intensidade do destaque aqui — sem mexer na lógica
do motor de legendas. Para usar um preset, defina `caption_style` em
`config/app_settings.json` (campo `caption_style` das Settings).

Cada preset é um `CaptionStyle`; adicionar um novo preset é criar uma
entrada nova neste dicionário.
"""

from __future__ import annotations

import logging

from core.subtitle_engine import CaptionStyle

logger = logging.getLogger(__name__)

PRESETS: dict[str, CaptionStyle] = {
    # Estilo clássico CapCut/Opus Clip: caixa alta, palavra ativa amarela.
    "viral_amarelo": CaptionStyle(
        font_name="Arial Black",
        primary_color="#FFFFFF",
        highlight_color="#FFD400",
        active_scale=110,
        uppercase=True,
    ),
    # Destaque vermelho agressivo, para conteúdo de impacto/ultraprovação.
    "impacto_vermelho": CaptionStyle(
        font_name="Arial Black",
        primary_color="#FFFFFF",
        highlight_color="#FF3B30",
        active_scale=115,
        uppercase=True,
    ),
    # Mais sóbrio: sem caixa alta, destaque ciano sutil.
    "clean_ciano": CaptionStyle(
        font_name="Arial",
        primary_color="#FFFFFF",
        highlight_color="#00E5FF",
        active_scale=105,
        uppercase=False,
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
