"""Testes da expressão de zoom e do canvas base (Fase 2)."""

from config.settings import OutputFormat
from core.video_processor import VideoInfo, VideoProcessor


def info(w=1280, h=720):
    return VideoInfo(width=w, height=h, duration=30.0)


def test_zoom_expression_sem_zooms():
    assert VideoProcessor._zoom_expression([]) == "1"


def test_zoom_expression_com_um_zoom():
    expr = VideoProcessor._zoom_expression([(1.0, 3.0, 0.15)])
    assert "(1+0.150" in expr
    assert "clip((t-1.000)/0.4,0,1)" in expr
    assert "clip((3.000+0.4-t)/0.4,0,1)" in expr


def test_zoom_expression_zooms_multiplos_multiplicam():
    expr = VideoProcessor._zoom_expression([(1.0, 2.0, 0.1), (5.0, 6.0, 0.2)])
    assert expr.count("*") >= 2


def test_base_canvas_vertical_com_horizontal():
    f = VideoProcessor()._base_canvas_filter(OutputFormat.VERTICAL, info())
    assert "boxblur" in f and "1080:1920" in f


def test_base_canvas_original():
    f = VideoProcessor()._base_canvas_filter(OutputFormat.ORIGINAL, info())
    assert f == "scale=trunc(iw/2)*2:trunc(ih/2)*2"
