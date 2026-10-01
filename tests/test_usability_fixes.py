"""Testes dos ajustes de usabilidade (v1.0.7): timeline, exportação e config."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def qt_app():
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


def test_settings_output_dir_roundtrip(tmp_path):
    from config.settings import Settings

    path = tmp_path / "settings.json"
    s = Settings()
    s.output_dir = "D:/Meus Videos"
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.output_dir == "D:/Meus Videos"


def test_exporter_uses_custom_output_dir(tmp_path):
    from config.settings import OutputFormat
    from core.exporter import Exporter

    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"x")
    custom = tmp_path / "saida-custom"
    result = Exporter().export(rendered, "meuvideo", OutputFormat.VERTICAL, output_dir=custom)
    assert result.parent == custom
    assert result.exists()
    assert result.name.startswith("meuvideo_vertical_")


def test_exporter_falls_back_when_custom_dir_unavailable(tmp_path):
    """Se a pasta de saída não puder ser criada, usa a padrão sem quebrar."""
    from config.settings import OutputFormat
    from core.exporter import Exporter

    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"x")
    blocked = tmp_path / "arquivo.txt" / "subpasta"  # pai é arquivo → OSError
    blocked.parent.write_text("não é pasta")
    result = Exporter().export(rendered, "meuvideo", OutputFormat.VERTICAL, output_dir=blocked)
    assert result.exists()


def test_timeline_widget_paints_cuts(qt_app):
    from core.edit_plan import Cut, EditPlan
    from ui.timeline_widget import EditTimelineWidget

    plan = EditPlan(duration=60.0)
    plan.cuts = [
        Cut(start=10.0, end=14.0, reason="silêncio"),
        Cut(start=30.0, end=33.0, reason="silêncio no final"),
    ]
    widget = EditTimelineWidget()
    widget.set_plan(plan)
    widget.resize(400, 56)
    from PyQt6.QtGui import QPixmap

    pix = QPixmap(widget.size())
    widget.render(pix)
    assert not pix.isNull()

    # clique no meio do primeiro corte emite o índice 0
    received = []
    widget.cutClicked.connect(received.append)
    widget.resize(400, 56)
    from PyQt6.QtCore import QPointF

    x = widget._time_to_x(12.0)
    class _Ev:
        def position(self):
            return QPointF(x, 28)
    widget.mousePressEvent(_Ev())
    assert received == [0]

    # set_cuts atualiza sem quebrar
    widget.set_cuts([{"start": 10.0, "end": 14.0, "approved": False}])
    widget.update()
