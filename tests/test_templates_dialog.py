"""Testes de integração da tela de templates."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def qt_app():
    """QApplication headless compartilhada pelos testes de UI."""
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


def test_templates_dialog_opens_and_applies_template(qt_app):
    """Smoke test da tela de templates: abrir, selecionar e aplicar."""
    from PyQt6.QtWidgets import QDialog

    from config.settings import Settings
    from core.templates import TemplateManager, apply_template
    from ui.templates_dialog import TemplatesDialog

    settings = Settings()
    manager = TemplateManager()
    dialog = TemplatesDialog(manager, settings)

    # Seleciona o template "podcast" e aplica
    idx = dialog.combo.findData("podcast")
    assert idx >= 0, "template podcast deve estar disponível"
    dialog.combo.setCurrentIndex(idx)
    dialog._apply_and_close()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert settings.active_template_id == "podcast"

    # Verifica que as configurações foram realmente aplicadas
    t = manager.get("podcast")
    apply_template(settings, t)
    assert settings.transition_type == t.transition_type
    assert settings.silence_gap_s == t.silence_gap_s
    assert settings.zoom_intensity == t.zoom_intensity


def test_templates_dialog_save_custom_template(qt_app, tmp_path):
    """Salvar um template customizado não pode levantar exceção."""
    from config.settings import Settings
    from core.templates import TemplateManager
    from ui.templates_dialog import TemplatesDialog

    settings = Settings()
    manager = TemplateManager(path=tmp_path / "templates.json")
    dialog = TemplatesDialog(manager, settings)

    dialog.font_edit.setText("Anton")
    dialog.primary_color.setText("#FF00FF")
    dialog.highlight_color.setText("#00FF00")

    custom = dialog._template_from_editor("meu_teste", "Meu Teste", "desc")
    manager.save_custom(custom)

    reloaded = manager.get("meu_teste")
    assert reloaded is not None
    assert reloaded.name == "Meu Teste"
    assert reloaded.font_name == "Anton"
