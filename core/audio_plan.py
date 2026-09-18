"""Plano de áudio da Fase 4: música de fundo + efeitos sonoros.

Representa as decisões de áudio (trilha, volume, normalização da voz e
eventos de SFX) na linha do tempo ORIGINAL — igual ao plano de edição.
Os timestamps são remapeados no render, após a aprovação na revisão.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SFX_KINDS = ("whoosh", "ding", "impact", "pop")
SFX_LABELS = {
    "whoosh": "Whoosh (transição)",
    "ding": "Ding (destaque)",
    "impact": "Impacto (zoom)",
    "pop": "Pop (ilustração)",
}
MAX_SFX_EVENTS = 30
SFX_MIN_GAP_S = 0.3  # distância mínima entre dois efeitos


@dataclass
class SfxEvent:
    """Um efeito sonoro em um momento da linha do tempo original."""

    kind: str
    timestamp: float
    origin: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "timestamp": round(self.timestamp, 3),
            "origin": self.origin,
        }


@dataclass
class AudioPlan:
    """Decisões de áudio sugeridas (e revisadas) para um vídeo."""

    mood: str = ""
    energy: float = 0.5
    music_path: Optional[Path] = None
    music_label: str = ""
    music_volume: float = 0.25  # volume linear da trilha (antes do ducking)
    normalize_voice: bool = True
    sfx: list[SfxEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mood": self.mood,
            "energy": self.energy,
            "music": str(self.music_path) if self.music_path else None,
            "music_label": self.music_label,
            "music_volume": self.music_volume,
            "normalize_voice": self.normalize_voice,
            "sfx": [e.to_dict() for e in self.sfx],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def suggest_sfx_from_plan(edit_plan, illustrations=()) -> list[SfxEvent]:
    """Deriva os efeitos sonoros do plano de edição sugerido.

    - whoosh no ponto de cada corte (a transição "voa" pro próximo trecho)
    - impacto no início de cada zoom (ênfase visual)
    - pop na entrada de cada ilustração
    Ordenado por timestamp e com espaçamento mínimo entre eventos.
    """
    events: list[SfxEvent] = []
    for cut in getattr(edit_plan, "cuts", []):
        events.append(
            SfxEvent(
                kind="whoosh",
                timestamp=cut.start,
                origin=f"corte {cut.start:.1f}s",
            )
        )
    for zoom in getattr(edit_plan, "zooms", []):
        events.append(
            SfxEvent(
                kind="impact",
                timestamp=zoom.start,
                origin=f"zoom {zoom.start:.1f}s",
            )
        )
    for m in illustrations or []:
        events.append(
            SfxEvent(
                kind="pop",
                timestamp=m.start,
                origin=f"ilustração {m.start:.1f}s",
            )
        )
    return _dedupe_sfx(events)


def remap_sfx(
    events: list[SfxEvent], edit_plan
) -> list[SfxEvent]:
    """Remapeia os SFX aprovados para a linha do tempo pós-cortes.

    Eventos que caem dentro de um corte são descartados (a fala/foto em
    volta deles foi removida).
    """
    remapped: list[SfxEvent] = []
    for e in events:
        if edit_plan is not None and edit_plan.cuts:
            # eventos exatamente na fronteira do corte são mantidos (o
            # whoosh DEVE tocar na emenda); só os internos são descartados
            if any(c.start < e.timestamp < c.end for c in edit_plan.cuts):
                continue
            ts = edit_plan.remap_time(e.timestamp)
        else:
            ts = e.timestamp
        remapped.append(
            SfxEvent(kind=e.kind, timestamp=ts, origin=e.origin)
        )
    return _dedupe_sfx(remapped)


def _dedupe_sfx(events: list[SfxEvent]) -> list[SfxEvent]:
    """Ordena, aplica espaçamento mínimo e limita a quantidade."""
    events = sorted(events, key=lambda e: e.timestamp)
    result: list[SfxEvent] = []
    for e in events:
        if e.kind not in SFX_KINDS:
            continue
        if result and e.timestamp - result[-1].timestamp < SFX_MIN_GAP_S:
            continue
        if len(result) >= MAX_SFX_EVENTS:
            break
        result.append(e)
    return result
