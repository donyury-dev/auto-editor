"""Baixa trilhas de exemplo gratuitas para assets/music/.

Uso:
    python scripts/download_sample_music.py

As faixas são de bancos com licença livre (Pixabay Audio / YouTube Audio
Library). O arquivo assets/music/README.md registra a fonte de cada uma.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = PROJECT_ROOT / "assets" / "music"

TRACKS = [
    {
        "id": "calm-podcast",
        "name": "Calm Podcast",
        "filename": "calm_podcast.mp3",
        "url": (
            "https://cdn.pixabay.com/download/audio/2022/05/27/"
            "audio_1808fbf07a.mp3?filename=calm-podcast-118715.mp3"
        ),
        "license": "Pixabay License — uso livre sem atribuição",
        "mood": "calma / podcast / entrevista",
    },
    {
        "id": "motivational-energy",
        "name": "Motivational Energy",
        "filename": "motivational_energy.mp3",
        "url": (
            "https://cdn.pixabay.com/download/audio/2022/10/14/"
            "audio_9939f792cb.mp3?filename=rock-energetic-490392.mp3"
        ),
        "license": "Pixabay License — uso livre sem atribuição",
        "mood": "energia / motivacional / viral",
    },
    {
        "id": "news-neutral",
        "name": "News Neutral",
        "filename": "news_neutral.mp3",
        "url": (
            "https://cdn.pixabay.com/download/audio/2022/01/18/"
            "audio_d0a13f69d2.mp3?filename=news-neutral-10125.mp3"
        ),
        "license": "Pixabay License — uso livre sem atribuição",
        "mood": "neutro / notícia / informativo",
    },
]

README_TEMPLATE = """# Trilhas de exemplo

As faixas abaixo são licenciadas pela Pixabay License e podem ser usadas em
projetos comerciais sem atribuição. Elas servem como demonstração para os
templates do Auto Editor. Você pode substituí-las por suas próprias trilhas
em `assets/music/`.

| Arquivo | Estilo | Fonte |
|---|---|---|
{rows}
"""


def download_track(track: dict) -> Path:
    """Baixa uma faixa e a salva em assets/music/."""
    dst = MUSIC_DIR / track["filename"]
    logger.info("Baixando %s", track["name"])
    req = Request(track["url"], headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=60) as resp, dst.open("wb") as f:
        shutil.copyfileobj(resp, f)
    logger.info("Salvo: %s", dst)
    return dst


def write_readme() -> None:
    rows = "\n".join(
        f"| {t['filename']} | {t['mood']} | {t['license']} |"
        for t in TRACKS
    )
    (MUSIC_DIR / "README.md").write_text(
        README_TEMPLATE.format(rows=rows), encoding="utf-8"
    )


def main() -> int:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for track in TRACKS:
            download_track(track)
        write_readme()
        logger.info("Todas as trilhas foram baixadas para %s", MUSIC_DIR)
    except Exception as exc:
        logger.error("Falha ao baixar trilhas: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
