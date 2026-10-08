"""Testes do diretor de edição (ai/director.py)."""

from ai.director import (
    SCENE_TRANSITIONS,
    apply_ai_direction,
    apply_heuristic_direction,
    sanitize_ai_direction,
)
from core.edit_plan import Cut, EditPlan


def make_plan(reasons=("silêncio de 0.5s",), duration=60.0):
    return EditPlan.from_dict(
        {
            "cuts": [
                {"start": float(i) * 5.0 + 1, "end": float(i) * 5.0 + 2,
                 "reason": r}
                for i, r in enumerate(reasons)
            ],
            "zooms": [],
            "transition_type": "corte",
            "transition_duration": 0.1,
            "duration": duration,
            "source": "teste",
        }
    )


def test_heuristica_varia_transicoes_em_mudanca_de_cenario():
    plan = make_plan(reasons=("mudança de cenário",) * 5)
    apply_heuristic_direction(plan)
    types = [c.transition_type for c in plan.cuts]
    assert types[0] == SCENE_TRANSITIONS[0]
    assert types[1] == SCENE_TRANSITIONS[1]
    assert len(set(types[:4])) == 4  # variadas, não tudo igual
    assert all(c.transition_duration == 0.3 for c in plan.cuts)


def test_respiro_comum_fica_seco():
    plan = make_plan(reasons=("silêncio de 0.5s", "silêncio de 1.2s"))
    apply_heuristic_direction(plan)
    assert all(c.transition_type == "" for c in plan.cuts)


def test_transicao_ja_definida_e_preservada():
    plan = make_plan(reasons=("mudança de cenário", "mudança de cenário"))
    plan.cuts[0].transition_type = "fade"
    plan.cuts[0].transition_duration = 0.2
    apply_heuristic_direction(plan)
    assert plan.cuts[0].transition_type == "fade"
    # o segundo corte (sem transição) entra no ciclo normalmente
    assert plan.cuts[1].transition_type == SCENE_TRANSITIONS[0]


def test_ai_direction_valida_e_aplica():
    plan = make_plan(reasons=("silêncio", "mudança de cenário"))
    data = {
        "cuts": [
            {"index": 0, "transition": "dissolve", "duration": 0.4,
             "sfx": "whoosh"},
            {"index": 99, "transition": "fade"},  # índice fora: ignorado
            {"index": 1, "transition": "redemoinho"},  # tipo inválido
        ],
        "sfx": [
            {"kind": "ding", "timestamp": 12.5},
            {"kind": "exploso", "timestamp": 20.0},  # kind inválido
            {"kind": "impact", "timestamp": -3},  # timestamp inválido
        ],
    }
    extra = apply_ai_direction(plan, data, duration=30.0)
    assert plan.cuts[0].transition_type == "dissolve"
    assert plan.cuts[0].transition_duration == 0.4
    assert plan.cuts[1].transition_type == ""  # inválido não aplicou
    assert [(e.kind, e.timestamp, e.origin) for e in extra] == [
        ("whoosh", plan.cuts[0].start, "IA"),
        ("ding", 12.5, "IA"),
    ]


def test_ai_direction_clampa_timestamp_e_duracao():
    plan = make_plan(reasons=("silêncio",), duration=10.0)
    data = {
        "cuts": [{"index": 0, "transition": "slideleft", "duration": 9.0}],
        "sfx": [{"kind": "pop", "timestamp": 55.0}],
    }
    decisions = sanitize_ai_direction(data, plan, duration=10.0)
    assert decisions["cuts"][0][1] == 1.0  # duração clampada
    assert decisions["sfx"][0].timestamp == 10.0  # dentro do vídeo
