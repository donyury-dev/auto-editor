"""Testes do servidor web (server/app.py).

A transcrição é simulada (monkeypatch em core.pipeline.TranscriptionEngine)
para cobrir o fluxo completo sem depender do Whisper nem de fala real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import server.app as webapp  # noqa: E402
from core.models import Transcript, Word  # noqa: E402


@pytest.fixture()
def tiny_video(tmp_path):
    """Vídeo 3s @10fps com cinza crescente."""
    import cv2

    path = tmp_path / "tiny.mp4"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48)
    )
    if not writer.isOpened():
        pytest.skip("OpenCV sem codec de escrita neste ambiente")
    for i in range(30):
        value = int((i * 8) % 255)
        frame = np.full((48, 64, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture()
def fake_transcript(monkeypatch):
    """Substitui a transcrição real por uma com fala simulada."""

    class FakeEngine:
        def __init__(self, **kwargs):
            pass

        def transcribe(self, media_path, progress=None):
            if progress:
                progress(1.0, "transcrição simulada")
            words = [
                Word(text="olha", start=0.2, end=0.5),
                Word(text="isso", start=0.5, end=0.8),
                Word(text="aqui", start=0.8, end=1.1),
                Word(text="tecnologia", start=1.3, end=1.9),
                Word(text="mudou", start=1.9, end=2.2),
            ]
            return Transcript(words=words, language="pt", duration=3.0)

    monkeypatch.setattr(
        "core.pipeline.TranscriptionEngine", FakeEngine, raising=True
    )


@pytest.fixture()
def client(tiny_video, fake_transcript):
    webapp.PROJECTS.clear()
    with TestClient(webapp.app) as c:
        resp = c.post("/api/projects", json={"path": str(tiny_video)})
        assert resp.status_code == 200
        project_id = resp.json()["id"]
        yield c, project_id
    webapp.PROJECTS.clear()


def test_health(client):
    c, _ = client
    assert c.get("/api/health").json() == {"ok": True}


def test_files_endpoint(client):
    c, _ = client
    resp = c.get("/api/files", params={"dir": str(PROJECT_ROOT)})
    data = resp.json()
    assert data["current"] == str(PROJECT_ROOT)
    assert "tests" in data["dirs"]


def test_analyze_produces_timeline(client):
    c, pid = client
    resp = c.post(f"/api/projects/{pid}/analyze")
    assert resp.status_code == 200
    state = webapp.PROJECTS[pid]
    # roda em thread; aguarda terminar
    import time

    for _ in range(120):
        if state.status in ("ready", "failed"):
            break
        time.sleep(0.25)
    assert state.status == "ready", state.error
    assert state.timeline["video"]["duration"] == pytest.approx(3.0, abs=0.2)
    assert len(state.timeline["captions"]) >= 1
    assert state.timeline["captions"][0]["words"][0]["text"] == "olha"


def test_timeline_persist(client):
    c, pid = client
    state = webapp.PROJECTS[pid]
    state.status = "ready"
    state.timeline = {
        "video": {"path": "x.mp4", "duration": 3.0, "width": 64, "height": 48},
        "cuts": [{"id": "c1", "start": 1.0, "end": 1.5, "reason": "teste"}],
        "zooms": [],
        "transition": {"type": "fade", "duration": 0.3},
        "captions": [
            {
                "id": "k1",
                "start": 0.2,
                "end": 1.1,
                "text": "olha isso aqui",
                "words": [
                    {"start": 0.2, "end": 0.5, "text": "olha"},
                    {"start": 0.5, "end": 0.8, "text": "isso"},
                    {"start": 0.8, "end": 1.1, "text": "aqui"},
                ],
            }
        ],
        "callouts": [{"id": "o1", "start": 1.3, "end": 2.2, "text": "TECNOLOGIA"}],
        "music": {"path": None, "label": "", "volume": 0.25},
        "sfx": [],
    }
    resp = c.put(
        f"/api/projects/{pid}/timeline",
        json={
            "cuts": [{"id": "c2", "start": 0.9, "end": 1.4, "reason": "editado"}],
            "zooms": [],
            "transition": {"type": "corte", "duration": 0.2},
            "captions": [
                {
                    "id": "k1",
                    "start": 0.2,
                    "end": 1.1,
                    "text": "olha isso aqui (editado)",
                    "words": [
                        {"start": 0.2, "end": 0.5, "text": "olha"},
                        {"start": 0.5, "end": 0.8, "text": "isso"},
                        {"start": 0.8, "end": 1.1, "text": "aqui"},
                    ],
                }
            ],
            "callouts": [{"id": "o1", "start": 1.3, "end": 2.2, "text": "FOCO"}],
            "music": {"path": None, "label": "", "volume": 0.3},
            "sfx": [],
        },
    )
    assert resp.status_code == 200
    assert state.timeline["cuts"][0]["id"] == "c2"
    assert state.timeline["transition"]["type"] == "corte"
    # call-out e legenda editados
    assert state.timeline["callouts"][0]["text"] == "FOCO"
    assert "editado" in state.timeline["captions"][0]["text"]


def test_apply_timeline_to_ctx_edits_transcript(client):
    c, pid = client
    state = webapp.PROJECTS[pid]
    state.status = "ready"
    from core.pipeline import PipelineContext
    from core.edit_plan import EditPlan
    from core.audio_plan import AudioPlan

    state.ctx = PipelineContext(
        input_path=Path("x.mp4"),
        settings=state.settings,
    )
    state.ctx.edit_plan = EditPlan(duration=3.0)
    state.ctx.audio_plan = AudioPlan()
    from core.models import Word

    state.ctx.transcript = Transcript(
        words=[Word(text="olha", start=0.2, end=0.5)], duration=3.0
    )
    state.timeline = {
        "video": {"path": "x.mp4", "duration": 3.0, "width": 64, "height": 48},
        "cuts": [{"id": "c1", "start": 1.0, "end": 1.5, "reason": ""}],
        "zooms": [],
        "transition": {"type": "fade", "duration": 0.3},
        "captions": [
            {
                "id": "k1",
                "start": 0.2,
                "end": 0.5,
                "text": "olá (corrigido)",
                "words": [{"start": 0.2, "end": 0.5, "text": "olha"}],
            }
        ],
        "callouts": [{"id": "o1", "start": 1.0, "end": 2.0, "text": "FOCO"}],
        "music": {"path": None, "label": "", "volume": 0.25},
        "sfx": [{"id": "s1", "kind": "whoosh", "timestamp": 1.0, "path": None}],
    }
    webapp._apply_timeline_to_ctx(state)
    assert state.ctx.edit_plan.cuts[0].start == 1.0
    assert state.ctx.illustrations[0].callout_text == "FOCO"
    # transcrição reconstruída com o texto corrigido
    assert state.ctx.transcript.words[0].text == "olá (corrigido)"
    assert state.ctx.audio_plan.sfx[0].kind == "whoosh"


def test_apply_timeline_limita_whooshes_automaticos_antigos(client):
    c, pid = client
    state = webapp.PROJECTS[pid]
    from core.audio_plan import AudioPlan
    from core.edit_plan import EditPlan
    from core.pipeline import PipelineContext

    state.ctx = PipelineContext(
        input_path=Path("x.mp4"),
        settings=state.settings,
    )
    state.ctx.edit_plan = EditPlan(duration=60.0)
    state.ctx.audio_plan = AudioPlan()
    state.ctx.transcript = Transcript(words=[], duration=60.0)
    state.timeline = {
        "video": {"path": "x.mp4", "duration": 60.0, "width": 64, "height": 48},
        "cuts": [],
        "zooms": [],
        "transition": {"type": "corte", "duration": 0.2},
        "captions": [],
        "callouts": [],
        "music": {"path": None, "label": "", "volume": 0.25},
        "sfx": [
            {"id": f"s{i}", "kind": "whoosh", "timestamp": float(i), "path": None}
            for i in range(8)
        ],
    }

    webapp._apply_timeline_to_ctx(state)
    assert len(state.ctx.audio_plan.sfx) == 2


def test_video_stream(client):
    c, pid = client
    state = webapp.PROJECTS[pid]
    state.status = "ready"
    resp = c.get(f"/api/projects/{pid}/video")
    assert resp.status_code == 200
    assert len(resp.content) > 1000


def test_library_endpoint(client):
    c, _ = client
    resp = c.get("/api/library")
    data = resp.json()
    assert "music" in data and "sfx" in data and "pack" in data
