"""Script de build do executável standalone.

Uso:
    python scripts/build_executable.py

Ele:
1. Verifica dependências (ffmpeg.exe, modelo Whisper small, trilhas).
2. Baixa o que estiver faltando.
3. Roda o PyInstaller.
4. Cria um pacote zip em dist/AutoEditor-windows.zip.
5. (Windows) Gera instalador .exe com Inno Setup se iscc estiver no PATH.

O script deve ser executado em uma máquina Windows com Python 3.10+
instalado (apenas para build).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist" / "AutoEditor"
ZIP_PATH = PROJECT_ROOT / "dist" / "AutoEditor-windows.zip"
ISS_PATH = PROJECT_ROOT / "installer.iss"


def run(cmd: list[str]) -> None:
    logger.info("Executando: %s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Comando falhou: {' '.join(cmd)}")


def ensure_ffmpeg() -> None:
    ffmpeg_exe = PROJECT_ROOT / "bin" / "ffmpeg" / "ffmpeg.exe"
    if ffmpeg_exe.exists():
        logger.info("FFmpeg já presente em %s", ffmpeg_exe)
        return
    logger.info("FFmpeg não encontrado; baixando...")
    run([sys.executable, "scripts/download_ffmpeg.py"])


def ensure_whisper() -> None:
    model_dir = PROJECT_ROOT / "models" / "whisper" / "small"
    if model_dir.exists() and any(model_dir.iterdir()):
        logger.info("Modelo Whisper small já presente em %s", model_dir)
        return
    logger.info("Modelo Whisper small não encontrado; baixando...")
    run([sys.executable, "scripts/download_whisper_model.py"])


def ensure_music() -> None:
    music_dir = PROJECT_ROOT / "assets" / "music"
    if any(music_dir.glob("*.mp3")):
        logger.info("Trilhas de exemplo já presentes em %s", music_dir)
        return
    logger.info("Trilhas não encontradas; baixando...")
    run([sys.executable, "scripts/download_sample_music.py"])


def _find_iscc() -> Path | None:
    """Localiza o compilador do Inno Setup, mesmo fora do PATH."""
    iscc = shutil.which("iscc")
    if iscc:
        return Path(iscc)
    common_paths = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 5\ISCC.exe"),
    ]
    for candidate in common_paths:
        if candidate.exists():
            return candidate
    return None


def build_installer() -> Path | None:
    """Tenta compilar o instalador Inno Setup."""
    iscc = _find_iscc()
    if not iscc:
        logger.warning(
            "Inno Setup Compiler (iscc.exe) não encontrado. "
            "O instalador .exe não será gerado; use a pasta dist/AutoEditor "
            "ou o arquivo zip. Baixe o Inno Setup em https://jrsoftware.org/isinfo.php"
        )
        return None

    version = os.environ.get("AUTO_EDITOR_VERSION", "1.0.0")
    logger.info("Gerando instalador com Inno Setup (%s) versão %s...", iscc, version)
    run([str(iscc), f"/DMyAppVersion={version}", str(ISS_PATH)])
    installer = PROJECT_ROOT / "dist" / f"AutoEditorSetup-{version}.exe"
    if installer.exists():
        logger.info("Instalador gerado: %s", installer)
        return installer
    return None


def build() -> None:
    ensure_ffmpeg()
    ensure_whisper()
    ensure_music()

    # Limpa build anterior
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    logger.info("Iniciando build com PyInstaller...")
    run([
        sys.executable, "-m", "PyInstaller",
        "build.pyinstaller.spec",
        "--clean", "--noconfirm",
    ])

    logger.info("Criando pacote zip...")
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in DIST_DIR.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(DIST_DIR.parent))
    logger.info("Pacote criado: %s", ZIP_PATH)

    installer = build_installer()
    if installer:
        logger.info("Pronto para distribuir: %s", installer)
    else:
        logger.info("Pronto para distribuir: %s", ZIP_PATH)


def main() -> int:
    try:
        build()
    except Exception as exc:
        logger.error("Build falhou: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
