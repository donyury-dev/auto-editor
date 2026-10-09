"""Testes da varredura: layout fallback e palavra na frente em close."""

from pathlib import Path

import numpy as np
import pytest

from core.layout_engine import pick_layouts
from core.models import Word


def words_from(text: str, start: float = 0.0, wps: float = 2.5) -> list:
    words = []
    t = start
    for w in text.split():
        words.append(Word(w, t, t + 0.4))
        t += 0.4 + 0.02
    return words


def test_layout_fallback_usa_frase_longa_sem_gatilho():
    # fala sem nenhuma palavra-gatilho ("explicação", "significa"…)
    words = words_from(
        "a tecnologia mudou nossas vidas de uma forma impressionante "
        "e continua mudando todos os dias em velocidade absurda"
    )
    layouts = pick_layouts(words, duration=words[-1].end + 1)
    assert layouts, "fallback deveria gerar cena de layout"


def test_layout_gatilho_ainda_funciona():
    words = words_from(
        "deixa eu dar um exemplo de como isso funciona na prática hoje"
    )
    layouts = pick_layouts(words, duration=words[-1].end + 1)
    assert layouts


class _FullMasker:
    """Máscara falsa: pessoa cobre o quadro inteiro (close de webcam)."""

    def alpha(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        return np.ones((h, w), dtype=float)


class _SmallMasker:
    """Máscara falsa: pessoa pequena no centro (plano aberto)."""

    def alpha(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        a = np.zeros((h, w), dtype=float)
        a[h // 3: 2 * h // 3, w // 3: 2 * w // 3] = 1.0
        return a


@pytest.fixture
def mini_video(tmp_path, monkeypatch):
    from core.ffmpeg_path import get_ffmpeg

    vf = tmp_path / "mini.mp4"
    import subprocess

    subprocess.run(
        [
            get_ffmpeg(), "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=2",
            "-pix_fmt", "yuv420p", str(vf),
        ],
        check=True,
    )
    return vf


def test_close_de_webhook_palavra_fica_na_frente(tmp_path, mini_video, monkeypatch):
    """Pessoa cobrindo o quadro: trecho descartado (sem overlay)."""
    import core.mask_engine as me
    from core.ffmpeg_path import get_ffmpeg

    monkeypatch.setattr(me, "PersonMasker", lambda p: _FullMasker())
    monkeypatch.setattr(me, "ensure_model", lambda: Path("fake.onnx"))
    segs = me.person_overlay_segments(
        mini_video, [(0.2, 1.8)], tmp_path, get_ffmpeg()
    )
    assert segs is None  # nenhum trecho com overlay — palavra na frente


def test_plano_aberto_palavra_fica_atras(tmp_path, mini_video, monkeypatch):
    """Pessoa pequena no quadro: overlay de pessoa é mantido."""
    import core.mask_engine as me
    from core.ffmpeg_path import get_ffmpeg

    monkeypatch.setattr(me, "PersonMasker", lambda p: _SmallMasker())
    monkeypatch.setattr(me, "ensure_model", lambda: Path("fake.onnx"))
    segs = me.person_overlay_segments(
        mini_video, [(0.2, 1.8)], tmp_path, get_ffmpeg()
    )
    assert segs and len(segs) == 1
