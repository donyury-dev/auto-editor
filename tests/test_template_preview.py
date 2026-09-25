"""Testes de geração de preview estático de templates."""

from __future__ import annotations

from PIL import Image

from core.template_preview import generate_template_preview
from core.templates import Template


def test_preview_generates_png(tmp_path):
    t = Template(id="test", name="Test", highlight_color="#FFD400")
    out = tmp_path / "preview.png"
    generate_template_preview(t, out, width=540, height=960)

    assert out.exists()
    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.size == (540, 960)


def test_preview_uses_template_colors(tmp_path):
    t = Template(
        id="test",
        name="Test",
        highlight_color="#00FF00",
        callout_color="#FF0000",
    )
    out = tmp_path / "preview2.png"
    generate_template_preview(t, out)

    with Image.open(out) as img:
        # Apenas garante que a imagem foi gerada sem exceção e tem tamanho padrão
        assert img.size == (1080, 1920)
