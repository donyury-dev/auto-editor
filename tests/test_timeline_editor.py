"""Smoke tests do editor de timeline."""

from __future__ import annotations

import os
from pathlib import Path

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


@pytest.fixture
def editor(qt_app):
    from core.audio_plan import AudioPlan
    from core.edit_plan import Cut, EditPlan, ZoomEffect
    from core.illustration_plan import IllustrationMoment
    from core.pack_manager import PackManager
    from config.settings import Settings
    from ui.timeline_editor import TimelineEditor

    settings = Settings.load()
    pm = PackManager(settings)
    plan = EditPlan(
        duration=10.0,
        cuts=[Cut(start=2.0, end=3.0, reason="silencio")],
        zooms=[ZoomEffect(start=5.0, end=6.0, intensity=0.1, reason="enfase")],
    )
    illus = [
        IllustrationMoment(
            start=1.0,
            end=3.0,
            kind="callout",
            prompt="casa",
            callout_text="CASA NA PRAIA",
        )
    ]
    editor = TimelineEditor(plan, illus, AudioPlan(), [], pm, ".verdent/uploads/teste de video.mp4")
    editor.show()
    qt_app.processEvents()
    yield editor
    editor.close()


def test_editor_opens_with_tracks(editor):
    assert len(editor.timeline.tracks) >= 2
    assert editor.timeline.track_by_type("video") is not None


def test_select_clip_updates_properties(editor):
    track = editor.timeline.track_by_type("video")
    clip = track.clips[0]
    editor.timeline_view.clipSelected.emit(track, clip)
    assert editor._selected_clip == clip
    assert editor.properties.clip == clip


def test_split_clip(editor):
    track = editor.timeline.track_by_type("video")
    n = len(track.clips)
    # seleciona o clipe [0-2] e posiciona playhead em 1.0
    clip = next(c for c in track.clips if c.start == 0.0 and c.end == 2.0)
    editor.timeline_view.clipSelected.emit(track, clip)
    editor.timeline.playhead = 1.0
    editor._split_at_playhead()
    assert len(track.clips) == n + 1


def test_delete_clip(editor):
    track = editor.timeline.track_by_type("text")
    n = len(track.clips)
    if n == 0:
        pytest.skip("sem clipes de texto")
    clip = track.clips[0]
    editor._on_clip_deleted(track, clip)
    assert len(track.clips) == n - 1


def test_adapters_roundtrip(editor):
    from core.timeline_model import TimelineToPlanAdapter

    adapter = TimelineToPlanAdapter(editor.timeline)
    plan = adapter.to_edit_plan()
    # o corte original 2-3 deve ser recuperado
    assert any(c.start == 2.0 and c.end == 3.0 for c in plan.cuts)


def test_timeline_view_paints(editor):
    from PyQt6.QtGui import QPixmap

    editor.timeline_view.grab()
    assert True
