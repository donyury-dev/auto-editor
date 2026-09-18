"""Motor de efeitos sonoros sintetizados localmente (Fase 4).

Whoosh, ding, impacto e pop são GERADOS por síntese (numpy + wave) —
sem assets externos, sem custos e sem questões de licença. Cada efeito
é gerado uma única vez e cacheado em cache/sfx/.
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

import numpy as np

from config.settings import CACHE_DIR

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100
SFX_CACHE_DIR = CACHE_DIR / "sfx"


def _write_wav(path: Path, samples: np.ndarray) -> Path:
    """Grava amostras float [-1, 1] como WAV mono 16-bit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return path


def _env_ad(n: int, attack: float, decay: float) -> np.ndarray:
    """Envelope de amplitude attack/decay (em segundos), pico 1.0."""
    t = np.arange(n) / SAMPLE_RATE
    total = attack + decay
    env = np.where(
        t < attack,
        t / max(attack, 1e-6),
        np.exp(-6.0 * (t - attack) / max(decay, 1e-6)),
    )
    env[t > total] = 0.0
    return env


def _one_pole_lowpass(x: np.ndarray, cutoffs: np.ndarray) -> np.ndarray:
    """Filtro passa-baixa simples com cutoff variável no tempo (sweep)."""
    y = np.empty_like(x)
    alpha = 1.0 - np.exp(-2.0 * np.pi * cutoffs / SAMPLE_RATE)
    prev = 0.0
    for i in range(len(x)):
        prev += alpha[i] * (x[i] - prev)
        y[i] = prev
    return y


def _gen_whoosh() -> np.ndarray:
    """Ruído com sweep de abertura: filtro abre e fecha (0.55s)."""
    dur = 0.55
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    noise = np.random.default_rng(42).standard_normal(n) * 0.8
    # cutoff sobe até o meio e desce (sensação de "passar voando")
    sweep = 400 + 3600 * np.sin(np.pi * np.minimum(t / dur, 1.0)) ** 2
    filtered = _one_pole_lowpass(noise, sweep)
    env = np.sin(np.pi * np.minimum(t / dur, 1.0)) ** 1.5
    return filtered * env * 0.9


def _gen_ding() -> np.ndarray:
    """Ding brilhante: parciais harmônicos com decaimento (0.9s)."""
    dur = 0.9
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    env = np.exp(-4.5 * t)
    ding = (
        0.55 * np.sin(2 * np.pi * 1568 * t)
        + 0.28 * np.sin(2 * np.pi * 2637 * t)
        + 0.12 * np.sin(2 * np.pi * 3951 * t)
    )
    out = ding * env
    out[: int(0.004 * SAMPLE_RATE)] *= np.linspace(
        0, 1, int(0.004 * SAMPLE_RATE)
    )
    return out * 0.7


def _gen_impact() -> np.ndarray:
    """Impacto grave: sweep 130→45 Hz com decaimento rápido (0.45s)."""
    dur = 0.45
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = 45 + 85 * np.exp(-t / 0.08)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    env = np.exp(-7.0 * t)
    body = np.sin(phase) * env
    click = (
        np.random.default_rng(7).standard_normal(n)
        * np.exp(-60.0 * t)
        * 0.25
    )
    return (body + click) * 0.95


def _gen_pop() -> np.ndarray:
    """Pop curto para entrada de ilustração (0.18s)."""
    dur = 0.18
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    freq = 380 + 500 * np.minimum(t / 0.05, 1.0)
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    env = np.exp(-18.0 * t)
    return np.sin(phase) * env * 0.6


_GENERATORS = {
    "whoosh": _gen_whoosh,
    "ding": _gen_ding,
    "impact": _gen_impact,
    "pop": _gen_pop,
}


def get_sfx(kind: str, cache_dir: Path | None = None) -> Path:
    """Retorna o WAV do efeito, sintetizando (e cacheando) se preciso."""
    if kind not in _GENERATORS:
        raise ValueError(f"Efeito sonoro desconhecido: {kind}")
    cache_dir = Path(cache_dir or SFX_CACHE_DIR)
    path = cache_dir / f"{kind}.wav"
    if path.exists() and path.stat().st_size > 0:
        return path
    logger.info("Sintetizando efeito sonoro '%s'…", kind)
    samples = _GENERATORS[kind]()
    return _write_wav(path, samples)
