"""Testes do helper de caminho do FFmpeg."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.ffmpeg_path import _find_executable, get_ffmpeg, get_ffprobe


def test_find_executable_prefers_bundled(tmp_path):
    bin_dir = tmp_path / "bin" / "ffmpeg"
    bin_dir.mkdir(parents=True)
    bundled = bin_dir / "ffmpeg.exe"
    bundled.write_text("fake")

    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path):
        found = _find_executable("ffmpeg")
        assert found == bundled


def test_find_executable_falls_back_to_path(tmp_path):
    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path), \
         patch("shutil.which", return_value=str(tmp_path / "system_ffmpeg")):
        found = _find_executable("ffmpeg")
        assert found == tmp_path / "system_ffmpeg"


def test_get_ffmpeg_raises_when_missing(tmp_path):
    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path), \
         patch("shutil.which", return_value=None):
        try:
            get_ffmpeg()
        except FileNotFoundError as exc:
            assert "ffmpeg" in str(exc).lower()
        else:
            raise AssertionError("deveria ter levantado FileNotFoundError")


def test_get_ffprobe_raises_when_missing(tmp_path):
    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path), \
         patch("shutil.which", return_value=None):
        try:
            get_ffprobe()
        except FileNotFoundError as exc:
            assert "ffprobe" in str(exc).lower()
        else:
            raise AssertionError("deveria ter levantado FileNotFoundError")
