"""Testes do helper de caminho do FFmpeg."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

from core.ffmpeg_path import _find_executable, get_ffmpeg, get_ffprobe


def test_find_executable_prefers_bundled(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin" / "ffmpeg"
    bin_dir.mkdir(parents=True)
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled = bin_dir / name
    bundled.write_text("fake")
    os.chmod(bundled, 0o755)
    monkeypatch.chdir(tmp_path)

    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path):
        found = _find_executable("ffmpeg")
        assert found == bundled


def test_find_executable_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path), \
         patch("shutil.which", return_value=str(tmp_path / "system_ffmpeg")):
        found = _find_executable("ffmpeg")
        assert found == tmp_path / "system_ffmpeg"


def test_find_executable_ignores_exe_outside_windows(tmp_path, monkeypatch):
    """Em Linux/Mac, um ffmpeg.exe do Windows não deve ser usado."""
    if sys.platform == "win32":
        return
    bin_dir = tmp_path / "bin" / "ffmpeg"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ffmpeg.exe").write_text("fake")
    monkeypatch.chdir(tmp_path)
    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path), \
         patch("shutil.which", return_value=str(tmp_path / "system_ffmpeg")):
        found = _find_executable("ffmpeg")
        assert found == tmp_path / "system_ffmpeg"


def test_get_ffmpeg_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path), \
         patch("shutil.which", return_value=None):
        try:
            get_ffmpeg()
        except FileNotFoundError as exc:
            assert "ffmpeg" in str(exc).lower()
        else:
            raise AssertionError("deveria ter levantado FileNotFoundError")


def test_get_ffprobe_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("core.ffmpeg_path._bundle_dir", return_value=tmp_path), \
         patch("shutil.which", return_value=None):
        try:
            get_ffprobe()
        except FileNotFoundError as exc:
            assert "ffprobe" in str(exc).lower()
        else:
            raise AssertionError("deveria ter levantado FileNotFoundError")
