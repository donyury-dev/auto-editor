"""Diretor de edição — decide transição e efeito sonoro por corte.

Substitui as regras fixas ("fade igual em tudo", "whoosh nos 2 primeiros
cortes") por decisões contextuais:

- Com provedor de IA ativo: a IA recebe os cortes/zooms/ilustrações e
  devolve, por corte, a transição ideal e o efeito sonoro apropriado
  (`apply_ai_direction`).
- Sem IA: direção heurística local (`apply_heuristic_direction`) — cortes
  em mudança de cenário ganham transições variadas (estilo anúncio);
  respiros comuns ficam SECOS, porque efeito em todo corte cansa.

O resto do programa consome o resultado pelo próprio `EditPlan`
(`Cut.transition_type`) e pela lista de SFX extras — nenhuma UI muda.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.audio_plan import SFX_KINDS, SfxEvent
from core.edit_plan import TRANSITION_TYPES, EditPlan

logger = logging.getLogger(__name__)

# Transições usadas nos cortes que coincidem com mudança de cenário
# (variadas de propósito — tudo igual fica monótono).
SCENE_TRANSITIONS = ("dissolve", "slideleft", "circleopen", "wipeleft")
SCENE_TRANSITION_DURATION = 0.3

# Teto de segurança para a saída da IA (mesma ideia de MAX_PLAN_ITEMS)
MAX_DIRECTION_SFX = 8


def apply_heuristic_direction(plan: EditPlan) -> None:
    """Direção local (sem rede): transições variadas só onde fazem sentido.

    - corte em mudança de cenário → transição variada do ciclo
    - respiro/pausa comum → corte seco (sem transição, sem efeito)
    - transição já definida pela IA/template é preservada
    """
    n = 0
    for c in plan.cuts:
        if "mudança de cenário" in (c.reason or ""):
            if not c.transition_type:
                c.transition_type = SCENE_TRANSITIONS[
                    n % len(SCENE_TRANSITIONS)
                ]
                c.transition_duration = SCENE_TRANSITION_DURATION
                n += 1


def sanitize_ai_direction(
    data: dict, plan: EditPlan, duration: Optional[float] = None
) -> dict:
    """Valida a saída da IA e a converte em decisões seguras.

    Esquema esperado (campos inválidos são descartados, nunca quebram):
    {
      "cuts": [{"index": 0, "transition": "dissolve", "duration": 0.3,
                "sfx": "whoosh"}],
      "sfx": [{"kind": "ding", "timestamp": 12.5}]
    }

    Retorna {"cuts": {índice: (transição, duração)}, "sfx": [SfxEvent]}.
    """
    if duration is None:
        duration = plan.duration
    if not isinstance(data, dict):
        return {"cuts": {}, "sfx": []}

    cut_decisions: dict[int, tuple[str, float]] = {}
    raw_cuts = data.get("cuts")
    if isinstance(raw_cuts, list):
        for item in raw_cuts:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index", -1))
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(plan.cuts):
                continue
            tt = str(item.get("transition", "") or "").strip().lower()
            if tt not in TRANSITION_TYPES or tt == "corte":
                # "corte" = manter seco (padrão); tipos desconhecidos caem fora
                continue
            try:
                td = float(item.get("duration", 0) or 0)
            except (TypeError, ValueError):
                td = 0.0
            td = min(1.0, max(0.1, td)) if td else 0.3
            cut_decisions[idx] = (tt, td)

    extra_sfx: list[SfxEvent] = []
    seen_ts: list[float] = []
    raw_sfx = data.get("sfx")
    if not isinstance(raw_sfx, list):
        raw_sfx = []
    # efeitos por corte também entram na lista (whoosh na emenda)
    for idx, (tt, _td) in cut_decisions.items():
        item = raw_cuts[idx] if isinstance(raw_cuts, list) else None
        kind = str((item or {}).get("sfx", "") or "").strip().lower()
        if kind in SFX_KINDS:
            extra_sfx.append(
                SfxEvent(
                    kind=kind,
                    timestamp=plan.cuts[idx].start,
                    origin="IA",
                )
            )
            seen_ts.append(plan.cuts[idx].start)
    for item in raw_sfx:
        if not isinstance(item, dict) or len(extra_sfx) >= MAX_DIRECTION_SFX:
            continue
        kind = str(item.get("kind", "") or "").strip().lower()
        if kind not in SFX_KINDS:
            continue
        try:
            ts = float(item.get("timestamp", -1))
        except (TypeError, ValueError):
            continue
        if ts < 0:
            continue
        ts = min(ts, max(0.0, duration))
        if any(abs(ts - t) < 0.3 for t in seen_ts):
            continue
        extra_sfx.append(SfxEvent(kind=kind, timestamp=ts, origin="IA"))
        seen_ts.append(ts)

    return {"cuts": cut_decisions, "sfx": extra_sfx}


def apply_ai_direction(
    plan: EditPlan, data: dict, duration: Optional[float] = None
) -> list[SfxEvent]:
    """Aplica a direção da IA ao plano e devolve os SFX extras sugeridos."""
    decisions = sanitize_ai_direction(data, plan, duration)
    for idx, (tt, td) in decisions["cuts"].items():
        c = plan.cuts[idx]
        c.transition_type = tt
        c.transition_duration = td
    return decisions["sfx"]
