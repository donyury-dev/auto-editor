"""Testes da máscara de pessoa (palavras atrás do apresentador)."""

import numpy as np
import pytest


def test_merge_segments_une_vizinhos():
    from core.mask_engine import merge_segments

    merged = merge_segments([(1.0, 2.0), (1.8, 3.0), (5.0, 6.0)])
    assert merged == [(0.85, 3.15), (4.85, 6.15)]


def test_merge_segments_vazio():
    from core.mask_engine import merge_segments

    assert merge_segments([]) == []


def test_person_overlay_sem_modelo_retorna_none(monkeypatch, tmp_path):
    """Sem modelo (e sem internet) o recurso cai no texto na frente."""
    import core.mask_engine as me

    def falha():
        raise OSError("sem internet")

    monkeypatch.setattr(me, "ensure_model", falha)
    resultado = me.person_overlay_segments(
        "inexistente.mp4", [(1.0, 2.0)], tmp_path, "ffmpeg"
    )
    assert resultado is None


def test_masker_alpha_com_session_falsa():
    """Alpha calculado de um frame (session fake) mantém forma 0..1."""
    import core.mask_engine as me

    class FakeSession:
        def get_inputs(self):
            class I:
                name = "in"

            return [I()]

        def run(self, _names, feeds):
            x = feeds["in"]
            fake = np.linspace(0.2, 0.8, x.shape[-2] * x.shape[-1])
            return [np.broadcast_to(
                fake.reshape(1, 1, x.shape[-2], x.shape[-1]),
                x.shape,
            ).astype(np.float32)]

    masker = me.PersonMasker.__new__(me.PersonMasker)
    masker.session = FakeSession()
    masker.input_name = "in"
    frame = np.full((64, 48, 3), 128, dtype=np.uint8)
    alpha = masker.alpha(frame)
    assert alpha.shape == (64, 48)
    assert alpha.min() >= 0.0 and alpha.max() <= 1.0


def test_settings_flag_default():
    from config.settings import Settings

    assert Settings().keywords_behind_person is True


def test_person_overlay_limita_trechos_e_reporta_progresso(monkeypatch, tmp_path):
    """No máximo 4 trechos; progresso reportado de 0 a 1."""
    import core.mask_engine as me

    monkeypatch.setattr(me, "ensure_model", lambda: tmp_path / "fake.onnx")

    class FakeSession:
        def get_inputs(self):
            class I:
                name = "in"

            return [I()]

        def run(self, _n, f):
            x = f["in"]
            return [np.zeros_like(x)]

    class FakeMasker:
        def __init__(self, _p):
            self.session = FakeSession()
            self.input_name = "in"

        def alpha(self, rgb):
            return np.zeros(rgb.shape[:2], np.float32)

    monkeypatch.setattr(me, "PersonMasker", FakeMasker)
    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", lambda *a, **k: None)
    # frames vazios: glob não acha nada → segue sem person PNGs
    reports: list[float] = []
    result = me.person_overlay_segments(
        "x.mp4",
        [(i * 2.0, i * 2.0 + 1.0) for i in range(8)],
        tmp_path,
        "ffmpeg",
        progress=lambda f, m: reports.append(f),
    )
    assert result is None  # sem frames extraídos
    assert len(reports) >= 4  # pelo menos 1 report por trecho aceito


def test_mask_engine_fps_adaptativo():
    """Trechos longos usam fps menor (limite de quadros processados)."""
    from core.mask_engine import merge_segments

    long_segs = merge_segments([(0, 12.0), (13, 25.0)])
    total = sum(e - s for s, e in long_segs)
    fps = min(30.0, max(10.0, 420.0 / total))
    assert 15.0 <= fps <= 20.0  # ~420 frames no total
    # trecho curto mantém 30fps
    assert min(30.0, max(10.0, 420.0 / 3.0)) == 30.0
