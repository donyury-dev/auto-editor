"""Resolve o caminho do ffmpeg/ffprobe no ambiente de desenvolvimento
ou dentro do executável PyInstaller.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _bundle_dir() -> Path:
    """Retorna o diretório raiz do app (funciona em dev e no bundle)."""
    if getattr(sys, "frozen", False):
        # PyInstaller extrai o one-dir ou one-file em _MEIPASS
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _find_executable(name: str) -> Path | None:
    """Procura o binário em locais conhecidos do projeto ou no PATH."""
    bundle = _bundle_dir()
    candidates = [
        bundle / "bin" / "ffmpeg" / f"{name}.exe",
        bundle / "bin" / "ffmpeg" / name,
        bundle / f"{name}.exe",
        bundle / name,
        Path.cwd() / "bin" / "ffmpeg" / f"{name}.exe",
        Path.cwd() / "bin" / "ffmpeg" / name,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    # Fallback para PATH do sistema
    found = shutil.which(name)
    if found:
        return Path(found)
    return None


def get_ffmpeg() -> Path:
    """Retorna o caminho do executável ffmpeg."""
    path = _find_executable("ffmpeg")
    if path is None:
        raise FileNotFoundError(
            "ffmpeg não encontrado. Verifique se o FFmpeg está embutido "
            "no pacote ou instalado no sistema."
        )
    return path


def get_ffprobe() -> Path:
    """Retorna o caminho do executável ffprobe."""
    path = _find_executable("ffprobe")
    if path is None:
        raise FileNotFoundError(
            "ffprobe não encontrado. Verifique se o FFmpeg está embutido "
            "no pacote ou instalado no sistema."
        )
    return path
