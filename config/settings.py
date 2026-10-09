"""Configurações gerais e caminhos do projeto."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    """Retorna a raiz do projeto em desenvolvimento ou no bundle PyInstaller."""
    if getattr(sys, "frozen", False):
        # PyInstaller extrai recursos em _MEIPASS no one-file/one-dir
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _project_root()


def _user_data_root() -> Path:
    """Diretório com permissão de escrita para dados do usuário.

    No bundle PyInstaller a pasta de instalação pode ser somente leitura
    (ex.: Program Files), então config/temp/output/logs/cache vivem em
    %APPDATA%\\AutoEditor. Em desenvolvimento, segue na raiz do projeto.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "AutoEditor"
    return PROJECT_ROOT


# Recursos somente leitura embutidos no pacote
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"

# Dados graváveis do usuário (fora da pasta de instalação no bundle)
DATA_DIR = _user_data_root()
CONFIG_DIR = DATA_DIR / "config"
TEMP_DIR = DATA_DIR / "temp"
OUTPUT_DIR = DATA_DIR / "output"
LOGS_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"  # sobrevive entre sessões (ex.: imagens)
PROVIDERS_CONFIG_PATH = CONFIG_DIR / "providers.json"
SETTINGS_PATH = CONFIG_DIR / "app_settings.json"

VERTICAL_RESOLUTION = (1080, 1920)  # Reels / TikTok / Shorts
HORIZONTAL_RESOLUTION = (1920, 1080)  # YouTube


def resolve_whisper_model(configured: str | None = None) -> str:
    """Escolhe o modelo Whisper adequado à máquina atual.

    Prioridade: variável de ambiente WHISPER_MODEL > configurado.
    Em servidores com pouca RAM (ex.: plano Starter do Render, 512 MB),
    o modelo 'small' estoura a memória e o processo é morto no meio da
    transcrição — nesses casos usa um modelo menor automaticamente.
    """
    env = os.environ.get("WHISPER_MODEL", "").strip()
    if env:
        return env
    model = (configured or "small").strip() or "small"
    total_gb = -1.0
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemTotal"):
                    total_gb = int(line.split()[1]) / (1024 * 1024)
                    break
    except (OSError, ValueError, IndexError):
        return model  # não é Linux ou não deu para ler — usa o configurado
    if total_gb < 0:
        return model
    if total_gb < 1.2:
        return "tiny"
    if total_gb < 3.0:
        return "base"
    return model


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
    # Multiplicador do tamanho da fonte da legenda (1.0 = padrão do preset).
    caption_scale: float = 1.0
    # Posição vertical da legenda: % da altura da tela, a partir da base.
    # 25 = um quarto da altura acima do rodapé (típico CapCut).
    caption_vertical_position: int = 25
    # Linhas de contexto da legenda: 1 = 3 linhas visíveis (antes/atual/depois),
    # 0 = apenas a linha ativa (legenda limpa, padrão CapCut).
    caption_context_lines: int = 0
    # Fase Ilustrações: fonte de B-roll (id em images/manager.py) e densidade
    illustration_provider: str = "local"  # default: placeholder local, sem custo
    illustration_density_s: float = 8.0  # intervalo mínimo entre ilustrações
    # Fase 4 (áudio): trilhas, efeitos sonoros e normalização da voz
    music_dir: str = ""  # pasta extra de trilhas (além de assets/music/)
    music_volume: float = 0.25  # volume linear da trilha antes do ducking
    sfx_enabled: bool = True  # efeitos sonoros automáticos (whoosh/ding/…)
    voice_normalize: bool = True  # loudnorm na voz ANTES do ducking
    # Palavras-chave animadas ficam atrás da pessoa (segmentação u2netp)
    keywords_behind_person: bool = True

    # Fase 6 (templates): parâmetros de ritmo de edição persistidos
    transition_type: str = "corte"
    transition_duration: float = 0.1
    silence_gap_s: float = 0.35
    zoom_intensity: float = 0.10
    zoom_spread_s: float = 6.0
    max_zooms: int = 4
    active_template_id: str = ""

    # Fase 7: pack externo de assets (HD externo, lido em runtime)
    pack_root: str = ""  # pasta raiz do pack (auto-detecta subpastas)
    pack_folders: dict = field(default_factory=dict)  # categoria → pasta
    # Pasta onde o vídeo final é salvo (vazio = pasta padrão do app)
    output_dir: str = ""

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
        pack_folders = data.get("pack_folders")
        if not isinstance(pack_folders, dict):
            pack_folders = {}
        return cls(
            output_format=output_format,
            whisper_model=str(data.get("whisper_model", "small")),
            max_words_per_chunk=int(data.get("max_words_per_chunk", 4)),
            max_chunk_duration=float(data.get("max_chunk_duration", 2.5)),
            caption_style=str(data.get("caption_style", "viral_amarelo")),
            caption_scale=float(data.get("caption_scale", 1.0)),
            caption_vertical_position=int(
                data.get("caption_vertical_position", 25)
            ),
            caption_context_lines=max(
                0, int(data.get("caption_context_lines", 0))
            ),
            illustration_provider=str(data.get("illustration_provider", "local")),
            illustration_density_s=float(
                data.get("illustration_density_s", 8.0)
            ),
            music_dir=str(data.get("music_dir", "")),
            music_volume=float(data.get("music_volume", 0.25)),
            sfx_enabled=bool(data.get("sfx_enabled", True)),
            voice_normalize=bool(data.get("voice_normalize", True)),
            transition_type=str(data.get("transition_type", "corte")),
            transition_duration=float(data.get("transition_duration", 0.1)),
            # 0.7 era o padrão antigo; migra para o novo (pega respiros)
            silence_gap_s=0.35
            if abs(float(data.get("silence_gap_s", 0.35)) - 0.7) < 1e-6
            else float(data.get("silence_gap_s", 0.35)),
            zoom_intensity=float(data.get("zoom_intensity", 0.10)),
            zoom_spread_s=float(data.get("zoom_spread_s", 6.0)),
            max_zooms=int(data.get("max_zooms", 4)),
            active_template_id=str(data.get("active_template_id", "")),
            pack_root=str(data.get("pack_root", "")),
            pack_folders=pack_folders,
            output_dir=str(data.get("output_dir", "")),
        )

    def save(self, path: Path | None = None) -> None:
        path = path or SETTINGS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["output_format"] = self.output_format.value
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
