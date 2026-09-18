"""Testes dos efeitos sonoros sintetizados (audio/sfx_engine.py)."""

import wave

import numpy as np

from audio.sfx_engine import SAMPLE_RATE, get_sfx


def _read_wav(path):
    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        frames = wf.getnframes()
        data = np.frombuffer(wf.readframes(frames), dtype=np.int16)
    return data.astype(np.float64) / 32768.0


def test_sintetiza_todos_os_efeitos(tmp_path):
    for kind in ("whoosh", "ding", "impact", "pop"):
        path = get_sfx(kind, cache_dir=tmp_path)
        assert path.exists()
        data = _read_wav(path)
        assert len(data) > 0
        # não pode ser silêncio nem clipping constante
        assert np.abs(data).max() > 0.3
        assert np.abs(data).max() <= 1.0


def test_cache_reaproveita_arquivo(tmp_path):
    p1 = get_sfx("ding", cache_dir=tmp_path)
    p2 = get_sfx("ding", cache_dir=tmp_path)
    assert p1 == p2


def test_efeito_desconhecido_levanta():
    try:
        get_sfx("explosao", cache_dir=None)
    except ValueError as exc:
        assert "desconhecido" in str(exc)
    else:
        raise AssertionError("deveria ter levantado ValueError")
