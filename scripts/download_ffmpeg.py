"""Baixa o FFmpeg estático para Windows e extrai ffmpeg.exe e ffprobe.exe.

Uso:
    python scripts/download_ffmpeg.py

Fonte: BtbN FFmpeg builds (GPL, win64).
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = PROJECT_ROOT / "bin" / "ffmpeg"
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)


def download_ffmpeg() -> tuple[Path, Path]:
    """Baixa e extrai ffmpeg.exe e ffprobe.exe para bin/ffmpeg/."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Baixando FFmpeg de %s", FFMPEG_URL)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        with urlopen(FFMPEG_URL) as resp, zip_path.open("wb") as f:
            shutil.copyfileobj(resp, f)
        logger.info("Extraindo FFmpeg...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)
        # Encontra os executáveis dentro da pasta extraída
        extracted = Path(tmp)
        for exe_name in ("ffmpeg.exe", "ffprobe.exe"):
            src = next(extracted.rglob(exe_name), None)
            dst = BIN_DIR / exe_name
            if src:
                shutil.copy2(src, dst)
                logger.info("%s copiado para %s", exe_name, dst)
            else:
                raise RuntimeError(f"{exe_name} não encontrado no zip do FFmpeg")
    return BIN_DIR / "ffmpeg.exe", BIN_DIR / "ffprobe.exe"


def main() -> int:
    try:
        download_ffmpeg()
        logger.info("FFmpeg pronto em %s", BIN_DIR)
    except Exception as exc:
        logger.error("Falha ao baixar FFmpeg: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
