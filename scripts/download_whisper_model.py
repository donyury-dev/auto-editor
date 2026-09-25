"""Baixa o modelo Whisper 'small' do Hugging Face para models/whisper/small.

Uso:
    python scripts/download_whisper_model.py

O modelo é necessário para rodar 100% offline no pacote standalone.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "whisper" / "small"


def download_model(model_size: str = "small") -> Path:
    """Garante que o modelo faster-whisper esteja disponível localmente."""
    from faster_whisper import download_model as fw_download

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Baixando modelo Whisper %s para %s", model_size, MODEL_DIR)
    path = fw_download(model_size, output_dir=str(MODEL_DIR))
    logger.info("Modelo salvo em: %s", path)
    return Path(path)


def main() -> int:
    try:
        download_model()
    except Exception as exc:
        logger.error("Falha ao baixar modelo Whisper: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
