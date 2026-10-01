"""Ponto de entrada do Auto Editor."""

from __future__ import annotations

import sys
import traceback

from core.logger import setup_logging


def _install_crash_handler(logger) -> None:
    """Registra exceções não tratadas em crash.log e avisa o usuário.

    Sem isso, no executável empacotado (console=False) um erro dentro de
    um slot do Qt aborta o processo sem nenhuma mensagem visível.
    """
    from config.settings import LOGS_DIR

    def _hook(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("Exceção não tratada:\n%s", text)
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            (LOGS_DIR / "crash.log").write_text(text, encoding="utf-8")
        except OSError:
            pass
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None,
                    "Erro inesperado",
                    "Ocorreu um erro inesperado:\n\n"
                    f"{exc_value}\n\n"
                    "Detalhes técnicos em logs/crash.log.",
                )
        except Exception:
            pass

    sys.excepthook = _hook


def main() -> None:
    logger = setup_logging()
    logger.info("Iniciando Auto Editor")

    from config.settings import CONFIG_DIR, LOGS_DIR, OUTPUT_DIR, TEMP_DIR

    for directory in (CONFIG_DIR, LOGS_DIR, OUTPUT_DIR, TEMP_DIR):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Não foi possível criar %s: %s", directory, exc)

    try:  # .env é opcional (fallback de API keys)
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    _install_crash_handler(logger)

    from PyQt6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
