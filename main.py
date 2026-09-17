"""Ponto de entrada do Auto Editor."""

from __future__ import annotations

import sys

from core.logger import setup_logging


def main() -> None:
    logger = setup_logging()
    logger.info("Iniciando Auto Editor")

    try:  # .env é opcional (fallback de API keys)
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    from PyQt6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
