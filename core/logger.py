"""Configuração de logging (console + arquivo rotativo em logs/)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config.settings import LOGS_DIR

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura o logger raiz uma única vez. Retorna o logger do app."""
    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED:
        return root

    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOGS_DIR / "autoeditor.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # sem permissão de escrita: segue só com console
        root.warning("Não foi possível criar log em arquivo: %s", exc)

    _CONFIGURED = True
    return logging.getLogger("autoeditor")
