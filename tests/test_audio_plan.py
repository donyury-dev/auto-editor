"""Testes do plano de áudio (core/audio_plan.py)."""

from core.audio_plan import (
    MAX_SFX_EVENTS,
    SfxEvent,
    remap_sfx,
    suggest_sfx_from_plan,
)
from core.edit_plan import Cut, EditPlan, ZoomEffect
from core.illustration_plan import IllustrationMoment


def make_plan(cuts=(), zooms=()):
    return EditPlan.from_dict(
        {
            "cuts": [
                {"start": s, "end": e, "reason": "teste"} for s, e in cuts
            ],
            "zooms": [
                {"start": s, "end": e, "intensity": 0.1, "reason": "teste"}
                for s, e in zooms
            ],
            "transition_type": "corte",
            "transition_duration": 0.1,
            "duration": 60.0,
            "source": "teste",
        }
    )


def test_sugere_whoosh_impacto_e_pop():
    plan = make_plan(cuts=[(10, 12)], zooms=[(20, 22)])
    illus = [IllustrationMoment(start=30.0, end=33.0, prompt="casa")]
    events = suggest_sfx_from_plan(plan, illus)
    kinds = [e.kind for e in events]
    assert kinds == ["whoosh", "impact", "pop"]
    assert events[0].timestamp == 10.0
    assert events[1].timestamp == 20.0
    assert events[2].timestamp == 30.0


def test_eventos_muito_proximos_sao_fundidos():
    plan = make_plan(cuts=[(10, 11)], zooms=[(10.1, 12)])
    events = suggest_sfx_from_plan(plan)
    # impacto a 10.1s está a <0.3s do whoosh a 10.0s: só o primeiro fica
    assert len(events) == 1
    assert events[0].kind == "whoosh"


def test_limite_maximo_de_eventos():
    plan = make_plan(
        cuts=[(i * 5.0, i * 5.0 + 1) for i in range(50)]
    )
    events = suggest_sfx_from_plan(plan)
    assert len(events) == MAX_SFX_EVENTS


def test_remap_descarta_dentro_do_corte_e_remapeia():
    plan = make_plan(cuts=[(10.0, 12.0)])
    events = [
        SfxEvent(kind="whoosh", timestamp=10.0, origin="corte"),
        SfxEvent(kind="impact", timestamp=15.0, origin="zoom"),
    ]
    result = remap_sfx(events, plan)
    # whoosh exatamente no corte (início) é mantido e remapeado p/ 10.0
    # impacto após o corte desloca 2s para trás
    assert len(result) == 2
    assert result[0].timestamp == 10.0
    assert result[1].timestamp == 13.0


def test_remap_descarta_evento_dentro_do_corte():
    plan = make_plan(cuts=[(10.0, 15.0)])
    events = [
        SfxEvent(kind="pop", timestamp=12.0, origin="ilustração"),
        SfxEvent(kind="ding", timestamp=20.0, origin="destaque"),
    ]
    result = remap_sfx(events, plan)
    assert len(result) == 1
    assert result[0].timestamp == 15.0  # 20 - 5
