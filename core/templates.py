"""Templates de estilo: presets editáveis e salváveis.

Um template agrupa, de uma só vez, as configurações visuais e de ritmo
que definem o "jeito" do vídeo final. Templates built-in vêm embarcados;
templates customizados são persistidos em `config/templates.json`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from config.settings import CONFIG_DIR, FONTS_DIR

logger = logging.getLogger(__name__)

TEMPLATES_PATH = CONFIG_DIR / "templates.json"


@dataclass
class Template:
    """Preset completo de estilo de edição."""

    id: str = ""
    name: str = ""
    description: str = ""
    # -- legendas --
    font_name: str = "Anton"
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFD400"
    outline: int = 5
    shadow: int = 2
    uppercase: bool = True
    active_scale: int = 135
    pop_animation: bool = True
    pop_overshoot: int = 10
    pop_duration_ms: int = 140
    caption_vertical_position: int = 25
    max_words_per_chunk: int = 4
    max_chunk_duration: float = 2.5
    strip_punctuation: bool = True
    # -- call-outs --
    callout_font_name: str = "Archivo Black"
    callout_color: str = "#FFD400"
    callout_scale_peak: int = 130
    callout_bounce: bool = True
    # -- ritmo de edição --
    transition_type: str = "corte"
    transition_duration: float = 0.1
    silence_gap_s: float = 0.7  # gaps maiores viram corte
    zoom_intensity: float = 0.10  # 0.10 = 10% de zoom no pico
    zoom_spread_s: float = 6.0  # distância mínima entre zooms
    max_zooms: int = 4
    # -- destaques/áudio --
    illustration_density_s: float = 8.0
    sfx_enabled: bool = True
    music_mood: str = "motivacional"
    music_energy: float = 0.6

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Template":
        return cls(**{k: data.get(k, v) for k, v in cls().to_dict().items()})


BUILT_IN_TEMPLATES: list[Template] = [
    Template(
        id="podcast",
        name="Podcast / Entrevista",
        description="Cortes suaves, zoom sutil, legendas claras e música calma.",
        font_name="Poppins ExtraBold",
        primary_color="#FFFFFF",
        highlight_color="#00E5FF",
        outline=3,
        shadow=1,
        uppercase=False,
        active_scale=112,
        pop_animation=False,
        caption_vertical_position=22,
        max_words_per_chunk=6,
        max_chunk_duration=3.5,
        callout_font_name="Poppins ExtraBold",
        callout_color="#00E5FF",
        callout_scale_peak=115,
        callout_bounce=False,
        transition_type="fade",
        transition_duration=0.25,
        silence_gap_s=1.0,
        zoom_intensity=0.06,
        zoom_spread_s=8.0,
        max_zooms=2,
        illustration_density_s=12.0,
        music_mood="calmo",
        music_energy=0.4,
    ),
    Template(
        id="motivacional",
        name="Motivacional / Viral",
        description="Cortes secos, zooms de impacto, cores quentes e energia alta.",
        font_name="Anton",
        primary_color="#FFFFFF",
        highlight_color="#FFD400",
        outline=6,
        shadow=3,
        uppercase=True,
        active_scale=140,
        pop_animation=True,
        pop_overshoot=14,
        pop_duration_ms=160,
        caption_vertical_position=28,
        max_words_per_chunk=3,
        max_chunk_duration=2.0,
        callout_font_name="Archivo Black",
        callout_color="#FFD400",
        callout_scale_peak=145,
        callout_bounce=True,
        transition_type="corte",
        transition_duration=0.05,
        silence_gap_s=0.5,
        zoom_intensity=0.14,
        zoom_spread_s=4.5,
        max_zooms=6,
        illustration_density_s=6.0,
        sfx_enabled=True,
        music_mood="energético",
        music_energy=0.8,
    ),
    Template(
        id="noticia",
        name="Notícia / Informativo",
        description="Tom sério, cortes limpos, legendas sóbrias e música neutra.",
        font_name="Archivo Black",
        primary_color="#FFFFFF",
        highlight_color="#FF3B30",
        outline=5,
        shadow=2,
        uppercase=True,
        active_scale=120,
        pop_animation=True,
        pop_overshoot=6,
        pop_duration_ms=100,
        caption_vertical_position=24,
        max_words_per_chunk=5,
        max_chunk_duration=2.8,
        callout_font_name="Archivo Black",
        callout_color="#FF3B30",
        callout_scale_peak=125,
        callout_bounce=True,
        transition_type="corte",
        transition_duration=0.1,
        silence_gap_s=0.8,
        zoom_intensity=0.08,
        zoom_spread_s=7.0,
        max_zooms=3,
        illustration_density_s=10.0,
        music_mood="neutro",
        music_energy=0.5,
    ),
]


class TemplateManager:
    """Carrega templates built-in e customizados salvos pelo usuário."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path or TEMPLATES_PATH)
        self._built_in: dict[str, Template] = {
            t.id: t for t in BUILT_IN_TEMPLATES
        }
        self._custom: dict[str, Template] = self._load()

    def _load(self) -> dict[str, Template]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    tid: Template.from_dict(tdata)
                    for tid, tdata in data.items()
                    if tid not in self._built_in
                }
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("templates.json inválido (%s); ignorando.", exc)
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {tid: t.to_dict() for tid, t in self._custom.items()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def list_templates(self) -> list[Template]:
        """Todos os templates disponíveis (built-in primeiro, depois custom)."""
        merged = {**self._built_in, **self._custom}
        return list(merged.values())

    def get(self, template_id: str) -> Optional[Template]:
        if template_id in self._custom:
            return self._custom[template_id]
        return self._built_in.get(template_id)

    def save_custom(self, template: Template) -> None:
        """Salva ou atualiza um template customizado."""
        if template.id in self._built_in:
            raise ValueError(
                f"Não é possível sobrescrever o template built-in '{template.id}'."
            )
        self._custom[template.id] = template
        self._save()

    def delete_custom(self, template_id: str) -> None:
        """Remove um template customizado."""
        if template_id in self._custom:
            del self._custom[template_id]
            self._save()

    def duplicate(self, source_id: str, new_id: str, new_name: str) -> Template:
        """Cria uma cópia editável de qualquer template."""
        source = self.get(source_id)
        if source is None:
            raise ValueError(f"Template não encontrado: {source_id}")
        data = source.to_dict()
        data["id"] = new_id
        data["name"] = new_name
        template = Template.from_dict(data)
        self.save_custom(template)
        return template


def apply_template(settings, template: Template) -> None:
    """Aplica um template nas Settings do app.

    Edita o objeto `settings` in-place.
    """
    # legendas
    settings.caption_style = _caption_preset_from_template(template)
    settings.caption_vertical_position = template.caption_vertical_position
    settings.max_words_per_chunk = template.max_words_per_chunk
    settings.max_chunk_duration = template.max_chunk_duration
    # destaques / áudio
    settings.illustration_density_s = template.illustration_density_s
    settings.sfx_enabled = template.sfx_enabled
    # ritmo de edição (valores usados pela heurística e podem influenciar a IA)
    settings.transition_type = template.transition_type
    settings.transition_duration = template.transition_duration
    settings.silence_gap_s = template.silence_gap_s
    settings.zoom_intensity = template.zoom_intensity
    settings.zoom_spread_s = template.zoom_spread_s
    settings.max_zooms = template.max_zooms


def ensure_caption_preset(template: Template) -> str:
    """Garante que exista um CaptionStyle para o template.

    Se já houver um preset built-in com mesma fonte + cor de destaque,
    reaproveita; caso contrário, registra um preset dinâmico.
    """
    from core.caption_styles import PRESETS, DEFAULT_STYLE
    from core.subtitle_engine import CaptionStyle

    for pid, preset in PRESETS.items():
        if (
            preset.font_name == template.font_name
            and preset.highlight_color == template.highlight_color
        ):
            return pid

    dynamic_id = f"template_{template.id}"
    if dynamic_id not in PRESETS:
        PRESETS[dynamic_id] = CaptionStyle(
            font_name=template.font_name,
            font_size_vertical=74,
            font_size_horizontal=58,
            primary_color=template.primary_color,
            highlight_color=template.highlight_color,
            outline=template.outline,
            shadow=template.shadow,
            uppercase=template.uppercase,
            active_scale=template.active_scale,
            pop_animation=template.pop_animation,
            pop_overshoot=template.pop_overshoot,
            pop_duration_ms=template.pop_duration_ms,
            strip_punctuation=template.strip_punctuation,
        )
    return dynamic_id


def _caption_preset_from_template(template: Template) -> str:
    return ensure_caption_preset(template)
