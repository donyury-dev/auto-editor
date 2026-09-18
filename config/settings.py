"""Configurações gerais e caminhos do projeto."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
TEMP_DIR = PROJECT_ROOT / "temp"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOGS_DIR = PROJECT_ROOT / "logs"
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
CACHE_DIR = PROJECT_ROOT / "cache"  # sobrevive entre sessões (ex.: imagens)
PROVIDERS_CONFIG_PATH = CONFIG_DIR / "providers.json"
SETTINGS_PATH = CONFIG_DIR / "app_settings.json"

VERTICAL_RESOLUTION = (1080, 1920)  # Reels / TikTok / Shorts
HORIZONTAL_RESOLUTION = (1920, 1080)  # YouTube


class OutputFormat(str, Enum):
    """Formato de saída do vídeo exportado."""

    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    ORIGINAL = "original"


@dataclass
class Settings:
    """Configurações persistentes do aplicativo."""

    output_format: OutputFormat = OutputFormat.VERTICAL
    whisper_model: str = "small"
    max_words_per_chunk: int = 4
    max_chunk_duration: float = 2.5
    caption_style: str = "viral_amarelo"  # id de um preset em core/caption_styles.py
    # Posição vertical da legenda: % da altura da tela, a partir da base.
    # 25 = um quarto da altura acima do rodapé (típico CapCut).
    caption_vertical_position: int = 25
    # Fase Ilustrações: fonte de B-roll (id em images/manager.py) e densidade
    illustration_provider: str = "local"  # default: placeholder local, sem custo
    illustration_density_s: float = 8.0  # intervalo mínimo entre ilustrações
    # Fase 4 (áudio): trilhas, efeitos sonoros e normalização da voz
    music_dir: str = ""  # pasta extra de trilhas (além de assets/music/)
    music_volume: float = 0.25  # volume linear da trilha antes do ducking
    sfx_enabled: bool = True  # efeitos sonoros automáticos (whoosh/ding/…)
    voice_normalize: bool = True  # loudnorm na voz ANTES do ducking

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or SETTINGS_PATH
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Falha ao ler configurações (%s); usando padrões.", exc)
            return cls()
        try:
            output_format = OutputFormat(data.get("output_format", "vertical"))
        except ValueError:
            output_format = OutputFormat.VERTICAL
        return cls(
            output_format=output_format,
            whisper_model=str(data.get("whisper_model", "small")),
            max_words_per_chunk=int(data.get("max_words_per_chunk", 4)),
            max_chunk_duration=float(data.get("max_chunk_duration", 2.5)),
            caption_style=str(data.get("caption_style", "viral_amarelo")),
            caption_vertical_position=int(
                data.get("caption_vertical_position", 25)
            ),
            illustration_provider=str(data.get("illustration_provider", "local")),
            illustration_density_s=float(
                data.get("illustration_density_s", 8.0)
            ),
            music_dir=str(data.get("music_dir", "")),
            music_volume=float(data.get("music_volume", 0.25)),
            sfx_enabled=bool(data.get("sfx_enabled", True)),
            voice_normalize=bool(data.get("voice_normalize", True)),
        )

    def save(self, path: Path | None = None) -> None:
        path = path or SETTINGS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["output_format"] = self.output_format.value
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
