"""Gerenciador da biblioteca de músicas de fundo (Fase 4).

Trilhas livres de direitos fornecidas pelo usuário: pasta embutida
`assets/music/` e/ou uma pasta extra configurável em Configurações.
Metadados por trilha via `music.json` na pasta (opcional):

    [{"file": "lofi.mp3", "mood": "calmo", "energy": 0.4}, ...]

Sem music.json, o clima é inferido por palavras-chave no nome do
arquivo ("energ", "upbeat" → energético; "calm", "lofi", "chill" →
calmo; etc.). Biblioteca vazia → sem música (nunca quebra o render).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.settings import ASSETS_DIR

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}

# palavras-chave no nome do arquivo → clima
_FILENAME_MOODS = (
    (("energ", "upbeat", "epic", "trap", "rock", "edm"), "energético"),
    (("motiv", "inspir", "corpor", "pop"), "motivacional"),
    (("calm", "lofi", "lo-fi", "chill", "ambient", "piano", "soft"), "calmo"),
    (("fun", "happy", "alegr", "comedy", "quirky"), "divertido"),
    (("tension", "suspense", "dark", "drama"), "tenso"),
    (("news", "notic", "podcast"), "neutro"),
)


@dataclass
class MusicTrack:
    path: Path
    mood: str = ""
    energy: float = 0.5

    @property
    def label(self) -> str:
        name = self.path.stem.replace("_", " ").replace("-", " ").strip()
        mood = f" [{self.mood}]" if self.mood else ""
        return f"{name}{mood}"


def _mood_from_filename(name: str) -> str:
    lower = name.lower()
    for keywords, mood in _FILENAME_MOODS:
        if any(k in lower for k in keywords):
            return mood
    return ""


class MusicManager:
    """Escaneia pastas de trilhas e seleciona por clima sugerido pela IA."""

    def __init__(self, extra_folders: Optional[list[Path]] = None) -> None:
        folders = [ASSETS_DIR / "music"]
        folders += [Path(f) for f in (extra_folders or []) if f]
        self._folders = folders
        self._tracks: Optional[list[MusicTrack]] = None

    def tracks(self) -> list[MusicTrack]:
        """Trilhas disponíveis (deduplicadas por caminho resolvido)."""
        if self._tracks is not None:
            return self._tracks
        seen: set[Path] = set()
        tracks: list[MusicTrack] = []
        for folder in self._folders:
            if not folder.is_dir():
                continue
            meta = self._load_metadata(folder / "music.json")
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                info = meta.get(path.name, {})
                tracks.append(
                    MusicTrack(
                        path=path,
                        mood=str(info.get("mood", "")) or _mood_from_filename(path.name),
                        energy=float(info.get("energy", 0.5)),
                    )
                )
        self._tracks = tracks
        return tracks

    @staticmethod
    def _load_metadata(meta_path: Path) -> dict:
        if not meta_path.exists():
            return {}
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(m.get("file", "")): m for m in data if isinstance(m, dict)}
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("music.json inválido em %s: %s", meta_path.parent, exc)
        return {}

    def pick(self, mood: str = "", energy: float = 0.5) -> Optional[MusicTrack]:
        """Escolhe a trilha que melhor casa com o clima sugerido."""
        tracks = self.tracks()
        if not tracks:
            return None
        mood = (mood or "").lower().strip()

        def score(t: MusicTrack) -> float:
            s = 0.0
            if t.mood and mood and t.mood.lower() == mood:
                s += 2.0
            elif t.mood and mood and t.mood.lower()[:4] == mood[:4]:
                s += 1.0
            s += 1.0 - abs(t.energy - energy)  # energia próxima
            return s

        return max(tracks, key=score)
