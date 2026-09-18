"""Plano de ilustrações (B-roll): momentos + prompts + imagens.

Gerado pela IA (ou heurística local), revisado pelo usuário na tela de
revisão e só então aplicado no render. Funções puras e testáveis, no
mesmo espírito de core/edit_plan.py.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MIN_MOMENT_S = 1.0  # duração mínima de uma ilustração na tela
MAX_MOMENTS = 12  # teto de segurança para saídas de LLM


@dataclass
class IllustrationMoment:
    """Uma ilustração sobreposta à fala (linha do tempo ORIGINAL)."""

    start: float
    end: float
    text: str = ""  # trecho da fala que gerou a imagem
    prompt: str = ""  # descrição usada para buscar/gerar
    image_path: Optional[Path] = None  # arquivo local (None = placeholder)
    source: str = ""  # quem forneceu a imagem (id do provedor)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "prompt": self.prompt,
            "image_path": str(self.image_path) if self.image_path else None,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IllustrationMoment":
        path = data.get("image_path")
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            text=str(data.get("text", "")),
            prompt=str(data.get("prompt", "")),
            image_path=Path(path) if path else None,
            source=str(data.get("source", "")),
        )


def moments_to_json(moments: list[IllustrationMoment], path: Path) -> Path:
    path = Path(path)
    path.write_text(
        json.dumps(
            [m.to_dict() for m in moments], indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return path


def moments_from_json(path: Path) -> list[IllustrationMoment]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [IllustrationMoment.from_dict(item) for item in data]


def validate_illustrations(
    moments: list[IllustrationMoment],
    duration: float,
    words: Optional[list] = None,
    density_s: float = 8.0,
) -> list[IllustrationMoment]:
    """Sanitiza a lista de momentos (vindo de LLM ou heurística).

    - limita a quantidade (MAX_MOMENTS)
    - clamp em [0, duration]; descarta inválidos/curtos demais
    - expande para bordas de palavra (não corta fala no meio)
    - aplica densidade mínima entre inícios (sem poluição visual)
    """
    valid: list[IllustrationMoment] = []
    for m in sorted(moments, key=lambda m: m.start)[:MAX_MOMENTS]:
        if m.end <= m.start or m.start >= duration:
            continue
        m.start = max(0.0, m.start)
        m.end = min(duration, m.end)
        if not m.prompt.strip():
            m.prompt = m.text.strip()
        if m.end - m.start < MIN_MOMENT_S:
            m.end = min(duration, m.start + MIN_MOMENT_S)
        valid.append(m)

    # expande para bordas de palavra (a imagem cobre a fala inteira)
    if words:
        spans = [(w.start, w.end) for w in words]
        for m in valid:
            for ws, we in spans:
                if ws <= m.start < we:
                    m.start = ws
                    break
            for ws, we in spans:
                if ws < m.end <= we:
                    m.end = we
                    break
            m.end = min(duration, m.end)

    # densidade: mantém o primeiro de cada janela de density_s
    kept: list[IllustrationMoment] = []
    for m in valid:
        if kept and m.start - kept[-1].start < density_s:
            continue
        kept.append(m)
    return kept
