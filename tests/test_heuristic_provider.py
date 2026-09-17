"""Testes do provedor heurístico local (sem API key)."""

from ai.heuristic_provider import HeuristicProvider
from core.edit_plan import EditPlan, validate_plan
from core.models import Word


def test_plano_com_silencios_vira_cortes():
    provider = HeuristicProvider()
    words = [
        Word("oi", 0.0, 0.5),
        Word("gente", 0.5, 1.0),
        Word("tudo", 2.0, 2.5),  # gap de 1.0s antes -> corte
        Word("bem", 2.5, 3.0),
        Word("obrigado", 4.5, 5.0),  # gap de 1.5s -> corte
    ]
    segments = [
        {"start": w.start, "end": w.end, "text": w.text} for w in words
    ]
    raw = provider.suggest_edit_plan("", segments, duration=5.5)
    assert len(raw["cuts"]) == 2  # silêncio final de 0.5s não vira corte
    assert raw["cuts"][0]["start"] == 1.0
    assert raw["cuts"][0]["end"] == 2.0
    assert raw["transition_type"] in ("fade",)


def test_plano_e_valido_apos_validate():
    provider = HeuristicProvider()
    words = [
        Word("palavra", float(i), float(i) + 0.4) for i in range(0, 30, 2)
    ]  # gaps de 1.6s entre todas
    segments = [
        {"start": w.start, "end": w.end, "text": w.text} for w in words
    ]
    raw = provider.suggest_edit_plan("", segments, duration=32.0)
    plan = validate_plan(EditPlan.from_dict(raw | {"duration": 32.0}))
    assert plan.final_duration < 32.0
    # nenhum corte sobrepõe palavra
    for c in plan.cuts:
        for w in words:
            assert not (c.start < w.end and c.end > w.start)


def test_zooms_limitados_a_4():
    provider = HeuristicProvider()
    words = [Word(f"enfa{i}", i * 2.0, i * 2.0 + 0.9) for i in range(10)]
    segments = [
        {"start": w.start, "end": w.end, "text": w.text} for w in words
    ]
    raw = provider.suggest_edit_plan("", segments, duration=20.0)
    assert len(raw["zooms"]) <= 4
