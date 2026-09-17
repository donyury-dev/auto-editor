"""Plano de edição da Fase 2: cortes, zooms e transições.

O plano é gerado pela IA (ou heurística local, sem API key), revisado pelo
usuário na tela de revisão e só então renderizado. Todas as funções de
mapeamento de tempo são puras e testáveis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Tipos de transição suportados (filtros xfade do FFmpeg)
TRANSITION_TYPES = [
    "corte",  # corte seco (sem xfade)
    "fade",
    "slideleft",
    "slideup",
    "circleopen",
    "dissolve",
    "pixelize",
    "wipeleft",
]

ZOOM_RAMP_S = 0.4  # duração da rampa de entrada/saída do zoom (suavização)
ZOOM_MIN_DURATION_S = 1.0  # duração mínima de um zoom para ser perceptível
MIN_CUT_S = 0.15  # cortes menores que isso são descartados
MAX_PLAN_ITEMS = 60  # teto de segurança para saídas de LLM


@dataclass
class Cut:
    """Intervalo a REMOVER do vídeo (linha do tempo original)."""

    start: float
    end: float
    reason: str = ""


@dataclass
class ZoomEffect:
    """Zoom punch-in centrado num trecho (linha do tempo original)."""

    start: float
    end: float
    intensity: float = 0.15  # 0.15 = 15% de zoom
    reason: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class EditPlan:
    """Plano completo de edição sugerido (sujeito a revisão do usuário)."""

    cuts: list[Cut] = field(default_factory=list)
    zooms: list[ZoomEffect] = field(default_factory=list)
    transition_type: str = "fade"  # aplicado nos pontos de corte
    transition_duration: float = 0.3
    source: str = "heurística local"  # quem gerou o plano
    duration: float = 0.0  # duração do vídeo original

    # ------------------------------------------------------------------
    # Serialização (salvar/carregar plano revisado)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "cuts": [
                {"start": c.start, "end": c.end, "reason": c.reason}
                for c in self.cuts
            ],
            "zooms": [
                {
                    "start": z.start,
                    "end": z.end,
                    "intensity": z.intensity,
                    "reason": z.reason,
                }
                for z in self.zooms
            ],
            "transition_type": self.transition_type,
            "transition_duration": self.transition_duration,
            "source": self.source,
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EditPlan":
        return cls(
            cuts=[
                Cut(
                    start=float(c["start"]),
                    end=float(c["end"]),
                    reason=str(c.get("reason", "")),
                )
                for c in data.get("cuts", [])
            ],
            zooms=[
                ZoomEffect(
                    start=float(z["start"]),
                    end=float(z["end"]),
                    intensity=float(z.get("intensity", 0.15)),
                    reason=str(z.get("reason", "")),
                )
                for z in data.get("zooms", [])
            ],
            transition_type=str(data.get("transition_type", "fade")),
            transition_duration=float(data.get("transition_duration", 0.3)),
            source=str(data.get("source", "heurística local")),
            duration=float(data.get("duration", 0.0)),
        )

    def save(self, path: Path) -> Path:
        import json

        path = Path(path)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "EditPlan":
        import json

        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    @property
    def total_cut_duration(self) -> float:
        return sum(c.end - c.start for c in self.cuts)

    @property
    def transition_count(self) -> int:
        """Quantidade de junções que encurtam a timeline (xfade)."""
        if self.transition_type == "corte":
            return 0
        return max(0, len(self.kept_segments()) - 1)

    @property
    def total_transition_duration(self) -> float:
        return self.transition_count * self.transition_duration

    @property
    def final_duration(self) -> float:
        return max(
            0.0,
            self.duration
            - self.total_cut_duration
            - self.total_transition_duration,
        )

    # ------------------------------------------------------------------
    # Mapeamento de tempo: original -> pós-cortes/transições
    # ------------------------------------------------------------------

    def cut_overlap_before(self, t: float) -> float:
        """Quanto tempo removido existe antes do instante t (parcial)."""
        removed = 0.0
        for c in self.cuts:
            if c.end <= t:
                removed += c.end - c.start
            elif c.start < t:
                removed += t - c.start
        return removed

    def remap_time(self, t: float) -> float:
        """Converte um instante da linha original para a pós-cortes.

        Instantes DENTRO de um corte colapsam para o início do corte
        (fronteira do segmento seguinte).
        """
        for c in self.cuts:
            if c.start <= t < c.end:
                t = c.start
                break
        transition_overlap = 0.0
        if self.transition_type != "corte":
            transition_overlap = sum(
                self.transition_duration
                for c in self.cuts
                if c.end <= t
            )
        return t - self.cut_overlap_before(t) - transition_overlap

    def kept_segments(self) -> list[tuple[float, float]]:
        """Intervalos mantidos na linha original, ordenados."""
        segments: list[tuple[float, float]] = []
        cursor = 0.0
        for c in sorted(self.cuts, key=lambda c: c.start):
            if c.start > cursor:
                segments.append((cursor, c.start))
            cursor = max(cursor, c.end)
        if cursor < self.duration:
            segments.append((cursor, self.duration))
        return segments


def validate_plan(plan: EditPlan) -> EditPlan:
    """Sanitiza um plano (vindo de LLM ou heurística).

    - limita o número de itens
    - ordena e mescla cortes sobrepostos
    - descarta cortes fora do vídeo ou minúsculos
    - encaixa cortes que cortariam palavras no meio (arredonda p/ borda)
    - descarta zooms sobrepostos a cortes ou fora do vídeo
    """
    plan.cuts = sorted(plan.cuts, key=lambda c: c.start)[:MAX_PLAN_ITEMS]
    plan.zooms = sorted(plan.zooms, key=lambda z: z.start)[:MAX_PLAN_ITEMS]
    duration = plan.duration

    # cortes válidos, sem sobreposição
    valid: list[Cut] = []
    for c in plan.cuts:
        if c.end <= c.start or c.start >= duration:
            continue
        c.start = max(0.0, c.start)
        c.end = min(duration, c.end)
        if c.end - c.start < MIN_CUT_S:
            continue
        if valid and c.start < valid[-1].end:  # sobreposto: mescla
            valid[-1].end = max(valid[-1].end, c.end)
            valid[-1].reason = valid[-1].reason or c.reason
        else:
            valid.append(c)
    plan.cuts = valid

    # zooms: dentro do vídeo e fora dos cortes
    kept: list[ZoomEffect] = []
    for z in plan.zooms:
        z.intensity = min(0.4, max(0.05, z.intensity))
        z.start = max(0.0, z.start)
        z.end = min(duration, z.end)
        if z.end - z.start < 0.3:
            continue
        overlaps_cut = any(
            z.start < c.end and z.end > c.start for c in plan.cuts
        )
        if overlaps_cut:
            continue
        kept.append(z)
    plan.zooms = kept

    if plan.transition_type not in TRANSITION_TYPES:
        plan.transition_type = "fade"
    plan.transition_duration = min(1.0, max(0.1, plan.transition_duration))
    return plan


def snap_cuts_to_word_gaps(
    cuts: list[Cut], words: list, min_gap: float = 0.05
) -> list[Cut]:
    """Ajusta cortes para não cortarem palavras no meio.

    Recebe a lista de palavras transcritas (core.models.Word). Cortes cujo
    início/fim cai dentro de uma palavra são movidos para a borda mais
    próxima (fim da palavra anterior / início da seguinte), desde que a
    duração do corte continue >= MIN_CUT_S.
    """
    if not words:
        return cuts
    spans = [(w.start, w.end) for w in words]

    snapped: list[Cut] = []
    for c in cuts:
        start, end = c.start, c.end
        # início deve cair num silêncio: se está numa palavra, empurra p/ frente
        for ws, we in spans:
            if ws < start < we:
                start = we
                break
        # fim: se está numa palavra, puxa p/ trás
        for ws, we in spans:
            if ws < end < we:
                end = ws
                break
        if end - start >= MIN_CUT_S:
            snapped.append(Cut(start=start, end=end, reason=c.reason))
    return snapped
