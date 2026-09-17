"""Testes da expressão de zoom e do canvas base (Fase 2)."""

from config.settings import OutputFormat
from core.video_processor import VideoInfo, VideoProcessor


def info(w=1280, h=720):
    return VideoInfo(width=w, height=h, duration=30.0)


def test_zoom_expression_sem_zooms():
    f, cx, cy = VideoProcessor._zoom_expressions([])
    assert f == "1"
    assert cx == "0.5"
    assert cy == "0.5"


def test_zoom_expression_com_um_zoom():
    f, cx, cy = VideoProcessor._zoom_expressions([(1.0, 3.0, 0.15, 0.5, 0.4)])
    assert "(1+0.150" in f
    assert "(0.5-0.5*cos(PI*clip((t-1.000)/2.000,0,1)))" in f
    assert "gte(t,1.000)*lte(t,3.000)" in cx


def test_zoom_expression_zooms_multiplicam():
    f, cx, cy = VideoProcessor._zoom_expressions([
        (1.0, 2.0, 0.1, 0.5, 0.4),
        (5.0, 6.0, 0.2, 0.6, 0.3),
    ])
    assert f.count("*") >= 2
    assert "cos(PI" in f


def test_base_canvas_vertical_com_horizontal():
    f = VideoProcessor()._base_canvas_filter(OutputFormat.VERTICAL, info())
    assert "boxblur" in f and "1080:1920" in f


def test_base_canvas_original():
    f = VideoProcessor()._base_canvas_filter(OutputFormat.ORIGINAL, info())
    assert f == "scale=trunc(iw/2)*2:trunc(ih/2)*2"
