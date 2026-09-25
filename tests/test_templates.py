"""Testes do módulo de templates de estilo."""

from __future__ import annotations

import pytest

from config.settings import Settings
from core import caption_styles
from core.templates import (
    BUILT_IN_TEMPLATES,
    Template,
    TemplateManager,
    apply_template,
    ensure_caption_preset,
)


@pytest.fixture
def manager(tmp_path):
    return TemplateManager(path=tmp_path / "templates.json")


def test_builtin_templates_loaded(manager):
    ids = {t.id for t in manager.list_templates()}
    assert {"podcast", "motivacional", "noticia"}.issubset(ids)


def test_get_builtin(manager):
    t = manager.get("motivacional")
    assert t is not None
    assert t.transition_type == "corte"
    assert t.zoom_intensity == 0.14


def test_save_custom_template(manager):
    custom = Template(
        id="meu_custom",
        name="Meu Custom",
        font_name="Anton",
        highlight_color="#FF00FF",
        silence_gap_s=0.4,
    )
    manager.save_custom(custom)

    reloaded = TemplateManager(path=manager.path)
    loaded = reloaded.get("meu_custom")
    assert loaded is not None
    assert loaded.name == "Meu Custom"
    assert loaded.silence_gap_s == 0.4


def test_cannot_overwrite_builtin(manager):
    t = manager.get("podcast")
    with pytest.raises(ValueError):
        manager.save_custom(t)


def test_delete_custom(manager):
    custom = Template(id="delete_me", name="Delete Me")
    manager.save_custom(custom)
    assert manager.get("delete_me") is not None

    manager.delete_custom("delete_me")
    assert manager.get("delete_me") is None


def test_duplicate_template(manager):
    copy = manager.duplicate("podcast", "podcast_leve", "Podcast Leve")
    assert copy.id == "podcast_leve"
    assert copy.font_name == "Poppins ExtraBold"
    assert manager.get("podcast_leve") is not None


def test_apply_template_updates_settings(manager):
    settings = Settings()
    t = manager.get("motivacional")
    apply_template(settings, t)

    assert settings.caption_style == "viral_amarelo"
    assert settings.transition_type == "corte"
    assert settings.silence_gap_s == 0.5
    assert settings.zoom_intensity == 0.14
    assert settings.max_zooms == 6
    assert settings.illustration_density_s == 6.0


def test_apply_podcast_template_uses_clean_ciano_or_dynamic(manager):
    settings = Settings()
    t = manager.get("podcast")
    apply_template(settings, t)

    # podcast usa Poppins ExtraBold + ciano, que bate com o preset clean_ciano
    assert settings.caption_style == "clean_ciano"


def test_ensure_caption_preset_reuses_builtin():
    t = Template(id="x", name="X", font_name="Anton", highlight_color="#FFD400")
    preset_id = ensure_caption_preset(t)
    assert preset_id == "viral_amarelo"


def test_ensure_caption_preset_creates_dynamic():
    t = Template(id="unico", name="Único", font_name="Foo", highlight_color="#123456")
    preset_id = ensure_caption_preset(t)
    assert preset_id == "template_unico"
    assert preset_id in caption_styles.PRESETS
    assert caption_styles.PRESETS[preset_id].font_name == "Foo"


def test_template_from_dict_roundtrip(manager):
    original = manager.get("noticia")
    data = original.to_dict()
    restored = Template.from_dict(data)
    assert restored == original
