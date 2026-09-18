"""Testes do plano de ilustrações (core/illustration_plan.py)."""

from core.illustration_plan import (
    IllustrationMoment,
    moments_from_json,
    moments_to_json,
    validate_illustrations,
)
from core.models import Word


def make_words():
    return [
        Word(text="imagina", start=2.0, end=2.4),
        Word(text="uma", start=2.4, end=2.6),
        Word(text="casa", start=2.6, end=3.0),
        Word(text="na", start=3.0, end=3.1),
        Word(text="praia", start=3.1, end=3.6),
        Word(text="no", start=3.6, end=3.7),
        Word(text="sol", start=3.7, end=4.0),
    ]


def test_validate_descarta_invalidos():
    moments = [
        IllustrationMoment(start=10.0, end=9.0, prompt="invertido"),
        IllustrationMoment(start=50.0, end=60.0, prompt="depois do fim"),
    ]
    result = validate_illustrations(moments, duration=30.0)
    assert result == []


def test_validate_clampa_negativo_para_zero():
    m = IllustrationMoment(start=-5.0, end=1.0, prompt="antes")
    result = validate_illustrations([m], duration=30.0)
    assert len(result) == 1
    assert result[0].start == 0.0


def test_validate_clampa_e_preenche_prompt():
    m = IllustrationMoment(start=2.0, end=30.0, text="casa na praia", prompt="")
    result = validate_illustrations([m], duration=10.0)
    assert len(result) == 1
    assert result[0].end == 10.0
    assert result[0].prompt == "casa na praia"


def test_validate_expande_para_bordas_de_palavra():
    words = make_words()
    m = IllustrationMoment(start=2.2, end=3.8, prompt="casa na praia")
    result = validate_illustrations([m], duration=10.0, words=words)
    # 2.2 está dentro de "imagina" (2.0-2.4) → expande p/ 2.0
    # 3.8 está dentro de "sol" (3.7-4.0) → expande p/ 4.0
    assert result[0].start == 2.0
    assert result[0].end == 4.0


def test_validate_densidade():
    moments = [
        IllustrationMoment(start=2.0, end=4.0, prompt="a"),
        IllustrationMoment(start=5.0, end=7.0, prompt="b"),
        IllustrationMoment(start=20.0, end=22.0, prompt="c"),
    ]
    result = validate_illustrations(moments, duration=30.0, density_s=8.0)
    # 5.0 está a 3s de 2.0 (< 8s): descartado; 20.0 fica
    assert [m.prompt for m in result] == ["a", "c"]


def test_validate_limite_max_moments():
    moments = [
        IllustrationMoment(start=i * 10.0, end=i * 10.0 + 2, prompt=f"p{i}")
        for i in range(20)
    ]
    result = validate_illustrations(moments, duration=1000.0, density_s=8.0)
    assert len(result) == 12  # MAX_MOMENTS


def test_serializacao_json(tmp_path):
    moments = [
        IllustrationMoment(
            start=1.0, end=3.0, text="oi", prompt="casa", source="local"
        )
    ]
    path = moments_to_json(moments, tmp_path / "illus.json")
    loaded = moments_from_json(path)
    assert len(loaded) == 1
    assert loaded[0].prompt == "casa"
    assert loaded[0].image_path is None
