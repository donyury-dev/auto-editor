"""Testes do motor de vídeo (construção de argumentos do FFmpeg).

Não exigem FFmpeg instalado: validam a montagem dos comandos, incluindo a
regressão do mapeamento de vídeo (saída sem faixa de vídeo).
"""

from config.settings import OutputFormat
from core.video_processor import VideoInfo, VideoProcessor


def video_info(w=1280, h=720, dur=30.0) -> VideoInfo:
    return VideoInfo(width=w, height=h, duration=dur)


def maps_of(args: list[str]) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == "-map"]


def test_todos_formatos_mapeiam_video_explicitamente():
    """Regressão: sem '-map 0:v:0' ou '-map [v]', a saída sai sem vídeo."""
    proc = VideoProcessor()
    for fmt in (
        OutputFormat.VERTICAL,
        OutputFormat.HORIZONTAL,
        OutputFormat.ORIGINAL,
    ):
        args = proc._build_filter_args(fmt, video_info(), "ass=filename='x.ass'")
        stream_maps = maps_of(args)
        assert stream_maps, f"sem -map para {fmt}"
        assert any(
            m in ("0:v:0", "[v]") for m in stream_maps
        ), f"vídeo não mapeado para {fmt}: {stream_maps}"


def test_vertical_com_fonte_horizontal_usa_fundo_desfocado():
    proc = VideoProcessor()
    args = proc._build_filter_args(
        OutputFormat.VERTICAL, video_info(1280, 720), "ass=filename='x.ass'"
    )
    assert "-filter_complex" in args
    fc = args[args.index("-filter_complex") + 1]
    assert "boxblur" in fc
    assert "1080:1920" in fc
    assert "[v]" in maps_of(args)


def test_horizontal_com_fonte_horizontal_usa_vf_simples():
    proc = VideoProcessor()
    args = proc._build_filter_args(
        OutputFormat.HORIZONTAL, video_info(1280, 720), "ass=filename='x.ass'"
    )
    assert "-vf" in args
    assert "1920:1080" in args[args.index("-vf") + 1]
    assert "0:v:0" in maps_of(args)


def test_original_apenas_normaliza_e_aplica_ass():
    proc = VideoProcessor()
    args = proc._build_filter_args(
        OutputFormat.ORIGINAL, video_info(1281, 721), "ass=filename='x.ass'"
    )
    vf = args[args.index("-vf") + 1]
    assert vf.startswith("scale=trunc(iw/2)*2")
    assert "ass=" in vf
