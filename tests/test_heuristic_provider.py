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
    assert raw["transition_type"] in ("corte", "fade")


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


def test_ilustracoes_gatilho_explicito():
    provider = HeuristicProvider()
    words = [
        Word("e", 0.0, 0.2),
        Word("imagina", 0.5, 1.0),
        Word("uma", 1.0, 1.2),
        Word("casa", 1.2, 1.6),
        Word("na", 1.6, 1.7),
        Word("praia", 1.7, 2.2),
        Word("no", 2.2, 2.3),
        Word("sunset", 2.3, 2.8),
    ]
    segments = [
        {"start": w.start, "end": w.end, "text": w.text} for w in words
    ]
    moments = provider.suggest_illustration_moments(
        "", segments, duration=10.0
    )
    assert len(moments) == 1
    m = moments[0]
    assert m["start"] == 0.5  # começa no gatilho
    assert m["end"] == 2.8  # cobre a frase
    # prompt: palavras de conteúdo, sem conectores
    assert "casa" in m["prompt"]
    assert "praia" in m["prompt"]
    assert "uma" not in m["prompt"].split()
    assert "no" not in m["prompt"].split()


def test_ilustracoes_respeitam_densidade():
    provider = HeuristicProvider()
    words = [
        Word("imagina", 0.5, 1.0),
        Word("cachorro", 1.0, 1.5),
        Word("correndo", 1.5, 2.0),
        Word("imagina", 4.0, 4.5),  # a 3.5s do primeiro: dentro da janela
        Word("gato", 4.5, 5.0),
        Word("dormindo", 5.0, 5.5),
        Word("pense", 30.0, 30.5),  # longe: passa
        Word("num", 30.5, 30.7),
        Word("castelo", 30.7, 31.2),
    ]
    segments = [
        {"start": w.start, "end": w.end, "text": w.text} for w in words
    ]
    moments = provider.suggest_illustration_moments(
        "", segments, duration=40.0, density_s=8.0
    )
    assert len(moments) == 2
    assert moments[0]["start"] == 0.5
    assert moments[1]["start"] == 30.0


def test_ilustracoes_sem_gatilho_nada_sugerido():
    provider = HeuristicProvider()
    words = [Word("eu", 0.0, 0.3), Word("gosto", 0.3, 0.8), Word("disso", 0.8, 1.2)]
    segments = [
        {"start": w.start, "end": w.end, "text": w.text} for w in words
    ]
    moments = provider.suggest_illustration_moments(
        "", segments, duration=5.0
    )
    assert moments == []
