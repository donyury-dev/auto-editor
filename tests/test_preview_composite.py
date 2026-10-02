"""Prévia do vídeo editado (v1.0.9): simulação de cortes e composição."""

from __future__ import annotations

import os

import numpy as np
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
def tiny_video(tmp_path):
    """Vídeo 3s @10fps com cinza crescente (detectável frame a frame)."""
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


# ----------------------------------------------------------------------
# Funções puras de composição
# ----------------------------------------------------------------------


def test_screen_blend_remove_fundo_preto():
    from ui.preview_widget import _screen_blend

    base = np.full((4, 4, 3), 100, dtype=np.uint8)
    preto = np.zeros((4, 4, 3), dtype=np.uint8)
    branco = np.full((4, 4, 3), 255, dtype=np.uint8)
    assert np.array_equal(_screen_blend(base, preto), base)
    assert (_screen_blend(base, branco) == 255).all()


def test_paste_image_sem_alpha_centra_imagem():
    import cv2

    from ui.preview_widget import _paste_image

    base = np.zeros((100, 100, 3), dtype=np.uint8)
    img_path = None
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "img.png"
        cv2.imwrite(str(img_path), np.full((20, 17, 3), 200, dtype=np.uint8))
        out = _paste_image(base, img_path)
    assert out[20, 50, 0] == 200  # área central recebeu a imagem


# ----------------------------------------------------------------------
# Simulação de cortes no player
# ----------------------------------------------------------------------


def test_mapeamento_corta_trecho_aprovado(qt_app, tiny_video):
    from ui.preview_widget import EditedPreviewWidget

    player = EditedPreviewWidget()
    assert player.load(tiny_video)
    assert player.display_duration() == pytest.approx(3.0, abs=0.2)

    player.set_cut_simulation(
        True, [{"start": 1.0, "end": 2.0, "approved": True}]
    )
    assert player.display_duration() == pytest.approx(2.0, abs=0.2)
    # tempo final 1.5s → original 2.5s (pulou o corte de 1–2s)
    player.set_time(1.5)
    assert player.source_time() == pytest.approx(2.5, abs=0.15)


def test_mapeamento_ignora_corte_rejeitado(qt_app, tiny_video):
    from ui.preview_widget import EditedPreviewWidget

    player = EditedPreviewWidget()
    assert player.load(tiny_video)
    player.set_cut_simulation(
        True, [{"start": 1.0, "end": 2.0, "approved": False}]
    )
    assert player.display_duration() == pytest.approx(3.0, abs=0.2)
    player.set_time(1.5)
    assert player.source_time() == pytest.approx(1.5, abs=0.15)


def test_simulacao_desligada_nao_altera_tempo(qt_app, tiny_video):
    from ui.preview_widget import EditedPreviewWidget

    player = EditedPreviewWidget()
    assert player.load(tiny_video)
    player.set_cut_simulation(False, [{"start": 1.0, "end": 2.0, "approved": True}])
    player.set_time(1.5)
    assert player.source_time() == pytest.approx(1.5, abs=0.15)


# ----------------------------------------------------------------------
# Edição de cortes na tela de revisão
# ----------------------------------------------------------------------


def _build_editor(qt_app, tiny_video):
    from core.edit_plan import EditPlan
    from ui.timeline_editor import TimelineEditor

    plan = EditPlan(duration=3.0)
    return TimelineEditor(plan, [], None, [], None, tiny_video)


def test_timeline_editor_adiciona_clipe(qt_app, tiny_video):
    editor = _build_editor(qt_app, tiny_video)
    video_track = editor.timeline.track_by_type("video")
    n0 = len(video_track.clips)
    editor.preview.set_source_time(0.5)
    # adiciona clipe de vídeo manualmente na faixa principal
    from core.timeline_model import Clip

    video_track.add_clip(
        Clip(kind="video", start=0.5, end=2.0, source_path=tiny_video)
    )
    assert len(video_track.clips) == n0 + 1


def test_clipe_na_timeline_reflete_duracao(qt_app, tiny_video):
    from core.timeline_model import Clip

    editor = _build_editor(qt_app, tiny_video)
    editor.timeline.track_by_type("video").add_clip(
        Clip(kind="video", start=0.3, end=0.9, source_path=tiny_video)
    )
    # a presença do clipe indica que esse trecho é mantido
    assert editor.preview.display_duration() == pytest.approx(3.0, abs=0.2)


def test_timeline_view_pinta(qt_app, tiny_video):
    from core.timeline_model import Timeline, Track, Clip
    from ui.timeline_view import TimelineView

    timeline = Timeline(duration=3.0)
    track = timeline.ensure_track("video")
    track.add_clip(Clip(kind="video", start=0.0, end=3.0, source_path=tiny_video))
    widget = TimelineView(timeline)
    widget.set_zoom(1.0)
    widget.set_playhead(1.2)
    widget.grab()  # força paintEvent sem erro
    assert True
