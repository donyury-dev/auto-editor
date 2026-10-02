"""Testes do modelo de timeline (core/timeline_model)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.audio_plan import AudioPlan, SfxEvent
from core.edit_plan import Cut, EditPlan, ZoomEffect
from core.illustration_plan import IllustrationMoment
from core.pack_manager import PackSuggestion
from core.timeline_model import (
    Clip,
    PlanToTimelineAdapter,
    Timeline,
    TimelineToPlanAdapter,
    Track,
)


def test_clip_split():
    c = Clip(kind="video", start=0.0, end=10.0, source_in=0.0, source_out=10.0)
    left, right = c.split_at(3.0)
    assert left.end == 3.0
    assert right.start == 3.0
    assert left.source_out == 3.0
    assert right.source_in == 3.0


def test_track_add_sorts_clips():
    t = Track(type="video")
    t.add_clip(Clip(start=5.0, end=6.0))
    t.add_clip(Clip(start=1.0, end=2.0))
    assert [c.start for c in t.clips] == [1.0, 5.0]


def test_plan_to_timeline_creates_video_segments_and_cuts():
    video = Path("/tmp/fake_video.mp4")
    plan = EditPlan(
        duration=10.0,
        cuts=[Cut(start=2.0, end=3.0, reason="silencio")],
        zooms=[ZoomEffect(start=5.0, end=6.0, intensity=0.1, reason="enfase")],
    )
    adapter = PlanToTimelineAdapter(video, 10.0)
    timeline = adapter.build(
        plan,
        illustrations=[],
        audio_plan=None,
        pack_suggestions=[],
    )

    video_track = timeline.track_by_type("video")
    assert video_track is not None
    assert len(video_track.clips) == 2  # [0-2], [3-10]
    assert video_track.clips[0].start == 0.0 and video_track.clips[0].end == 2.0
    assert video_track.clips[1].start == 3.0 and video_track.clips[1].end == 10.0

    # zoom armazenado como meta no clipe que o contém
    clip = video_track.clips[1]
    assert "zooms" in clip.meta
    assert clip.meta["zooms"][0]["start"] == 5.0


def test_plan_to_timeline_callout_and_image():
    video = Path("/tmp/fake_video.mp4")
    plan = EditPlan(duration=10.0)
    illustrations = [
        IllustrationMoment(
            start=1.0, end=3.0, kind="callout", prompt="casa", callout_text="CASA"
        ),
        IllustrationMoment(
            start=4.0,
            end=6.0,
            kind="image",
            prompt="praia",
            image_path="/tmp/praia.png",
        ),
    ]
    adapter = PlanToTimelineAdapter(video, 10.0)
    timeline = adapter.build(plan, illustrations, None, [])

    text_track = timeline.track_by_type("text")
    overlay_track = timeline.track_by_type("overlay")
    assert text_track is not None and len(text_track.clips) == 1
    assert text_track.clips[0].kind == "callout"
    assert text_track.clips[0].text == "CASA"
    assert overlay_track is not None and len(overlay_track.clips) == 1
    assert overlay_track.clips[0].kind == "image"


def test_timeline_to_edit_plan_recovers_cuts():
    timeline = Timeline(duration=10.0)
    video = timeline.ensure_track("video")
    video.add_clip(Clip(kind="video", start=0.0, end=2.0))
    video.add_clip(Clip(kind="video", start=3.0, end=10.0))

    adapter = TimelineToPlanAdapter(timeline)
    plan = adapter.to_edit_plan()
    assert len(plan.cuts) == 1
    assert plan.cuts[0].start == 2.0 and plan.cuts[0].end == 3.0


def test_timeline_to_audio_plan_and_pack():
    timeline = Timeline(duration=10.0)
    music = timeline.ensure_track("music")
    music.add_clip(
        Clip(kind="music", start=0.0, end=10.0, source_path=Path("/tmp/m.mp3"), volume=0.3)
    )
    sfx = timeline.ensure_track("sfx")
    sfx.add_clip(Clip(kind="sfx", start=1.0, end=2.5, meta={"kind": "whoosh"}))
    overlay = timeline.ensure_track("overlay")
    overlay.add_clip(
        Clip(
            kind="overlay",
            start=2.0,
            end=4.0,
            source_path=Path("/tmp/o.mp4"),
            meta={"category": "overlays"},
        )
    )

    adapter = TimelineToPlanAdapter(timeline)
    audio = adapter.to_audio_plan()
    assert str(audio.music_path) == "/tmp/m.mp3"
    assert audio.music_volume == 0.3
    assert len(audio.sfx) == 1
    pack = adapter.to_pack_suggestions()
    assert len(pack) == 1
    assert pack[0].category == "overlays"
