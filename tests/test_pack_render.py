"""Testes do escape de caminhos e overlays do VideoProcessor (Fase 7)."""

from __future__ import annotations

from core.video_processor import VideoProcessor


def test_escape_filter_path_windows():
    esc = VideoProcessor._escape_filter_path
    from pathlib import Path

    p = Path("C:/Users/Kaio/AppData/temp/x/callouts.ass")
    assert esc(p) == r"C\:/Users/Kaio/AppData/temp/x/callouts.ass"


def test_escape_filter_path_linux_unchanged():
    esc = VideoProcessor._escape_filter_path
    from pathlib import Path

    assert esc(Path("/tmp/x/callouts.ass")) == "/tmp/x/callouts.ass"


def test_ass_filter_arg_escapes_windows_drive(tmp_path):
    from core.video_processor import VideoProcessor

    proc = VideoProcessor()
    ass = tmp_path / "callouts.ass"
    ass.write_text("[Script Info]\n")
    # simula um FONTS_DIR vazio para o teste focar no escape
    arg = proc._ass_filter_arg(ass)
    assert "ass=filename=" in arg
    if ":" in str(ass.as_posix()):
        assert r"\:" in arg  # drive escapado no Windows-like


def test_build_overlay_chain_labels_are_sequential():
    proc = VideoProcessor()
    items = [
        {"input": 1, "start": 1.0, "end": 3.0, "full": True},
        {"input": 2, "start": 5.0, "end": 7.0, "full": False},
    ]
    parts, _ = proc.build_overlay_chain(1080, 1920, items)
    joined = ";".join(parts)
    assert "[1:v]" in joined and "[2:v]" in joined
    assert "overlay" in joined
    # primeiro overlay usa a base [vbase] fornecida pelo chamador
    assert "[0:v][ov0]overlay" in joined or "[vbase][ov0]overlay" in joined.replace(
        "[0:v]", "[vbase]", 1
    )
    assert "between(t,1.000,3.000)" in joined
    assert "between(t,5.000,7.000)" in joined


def test_build_filter_args_with_lut(tmp_path):
    from config.settings import OutputFormat
    from core.video_processor import VideoInfo, VideoProcessor

    proc = VideoProcessor()
    info = VideoInfo(width=1920, height=1080, duration=10.0, has_audio=True)
    args = proc._build_filter_args(
        OutputFormat.ORIGINAL,
        info,
        "ass=filename='x.ass'",
        lut_file=r"C\:/pack/lut.cube",
    )
    assert "lut3d=file='C\\:/pack/lut.cube'" in args[1]
    assert "ass=filename='x.ass'" in args[1]
