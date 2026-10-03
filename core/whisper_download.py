"""Download seguro do modelo Whisper no ambiente do usuário.

Esse modulo e usado pelo executavel standalone quando o modelo nao esta
embutido no instalador (versao lite). Ele baixa o modelo para a pasta de
dados do usuario (%APPDATA%\\AutoEditor\\models\\whisper no Windows) e mostra
progresso via callback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


def _user_models_dir() -> Path:
    """Pasta de modelos gravável fora do bundle."""
    import sys

    from config.settings import DATA_DIR

    return DATA_DIR / "models" / "whisper"


def ensure_whisper_model(
    model_size: str = "small",
    progress: Optional[ProgressFn] = None,
) -> Path:
    """Garante que o modelo faster-whisper esteja disponível localmente.

    Se já existir na pasta de dados do usuário, retorna o caminho.
    Caso contrário, faz download do Hugging Face e salva nessa pasta.
    """
    from faster_whisper import download_model as fw_download

    target_dir = _user_models_dir() / model_size
    marker = target_dir / "model.bin"
    if marker.exists():
        logger.info("Modelo Whisper %s encontrado em %s", model_size, target_dir)
        return target_dir

    if progress:
        progress(0.0, f"baixando modelo Whisper '{model_size}'…")
    target_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Baixando modelo Whisper %s para %s", model_size, target_dir)
    try:
        fw_download(model_size, output_dir=str(target_dir))
    except Exception as exc:
        logger.error("Falha ao baixar modelo Whisper: %s", exc)
        raise RuntimeError(
            f"Não foi possível baixar o modelo Whisper '{model_size}'. "
            "Verifique sua conexão e tente novamente."
        ) from exc
    if not marker.exists():
        raise RuntimeError(
            "Download do modelo concluído, mas model.bin não foi encontrado."
        )
    if progress:
        progress(1.0, f"modelo '{model_size}' pronto")
    logger.info("Modelo salvo em: %s", target_dir)
    return target_dir
