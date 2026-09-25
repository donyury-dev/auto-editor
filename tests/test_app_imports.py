"""Testes de importação da aplicação.

Garante que a janela principal (e suas dependências) possa ser importada
sem erros de módulo do Qt. Erros de display/libEGL são ignorados em
ambientes sem servidor gráfico.
"""

from __future__ import annotations

import os
import sys

import pytest


@pytest.fixture(scope="session")
def qt_app():
    """Cria uma QApplication headless para os testes de inicialização."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
    except ImportError as exc:
        msg = str(exc).lower()
        if "libegl" in msg or "platform plugin" in msg or "display" in msg:
            pytest.skip(f"ambiente sem display/libEGL: {exc}")
        raise
    return app


def test_main_window_imports_without_qt_module_error():
    """Se main_window importar errado (ex: QUrl de QtGui), falha aqui."""
    # Força plataforma headless para evitar erro de display em CI sem X11
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    try:
        from ui.main_window import MainWindow  # noqa: F401
    except ImportError as exc:
        msg = str(exc).lower()
        # Em ambientes sem bibliotecas gráficas (como este container) o Qt
        # pode falhar ao carregar libEGL. Isso não é um erro de importação
        # do código do app e sim do ambiente, então pulamos o teste.
        if "libegl" in msg or "platform plugin" in msg or "display" in msg:
            pytest.skip(f"ambiente sem display/libEGL: {exc}")
        raise


def test_main_window_initializes_without_exception(qt_app):
    """Smoke test da construção completa da janela principal."""
    from ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.centralWidget() is not None
        assert window.windowTitle()
        qt_app.processEvents()
    finally:
        window.close()


def test_qurl_is_in_qtcore_not_qtgui():
    """Confirma a localização correta das classes do Qt."""
    from PyQt6.QtCore import QUrl  # noqa: F401

    with pytest.raises(ImportError):
        from PyQt6.QtGui import QUrl  # type: ignore[no-redef] # noqa: F401
