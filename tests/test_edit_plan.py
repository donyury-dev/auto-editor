"""Testes do plano de edição (Fase 2): remapeamento, validação, snap."""

import pytest

from core.edit_plan import (
    Cut,
    EditPlan,
    ZoomEffect,
    snap_cuts_to_word_gaps,
    validate_plan,
)
from core.models import Word


def make_plan(cuts=None, duration=100.0):
    return EditPlan(cuts=cuts or [], duration=duration)


def test_remap_time_sem_cortes_e_identidade():
    plan = make_plan()
    assert plan.remap_time(42.0) == 42.0


def test_remap_time_antes_durante_e_depois_do_corte():
    plan = make_plan([Cut(10.0, 15.0)])
    assert plan.remap_time(5.0) == 5.0  # antes
    assert plan.remap_time(12.0) == 10.0  # dentro: colapsa p/ início do corte
    # xfade encurta a junção em transition_duration.
    assert plan.remap_time(20.0) == 14.7  # remove 5s + 0.3s de transição


def test_remap_time_cortes_multiplos():
    plan = make_plan([Cut(10, 12), Cut(20, 25)])
    assert plan.remap_time(30.0) == 30.0 - 2 - 5 - 2 * 0.3


def test_kept_segments():
    plan = make_plan([Cut(10, 20), Cut(30, 35)], duration=40)
    assert plan.kept_segments() == [(0, 10), (20, 30), (35, 40)]


def test_duracoes():
    plan = make_plan([Cut(10, 20), Cut(30, 35)], duration=40)
    assert plan.total_cut_duration == 15.0
    assert plan.final_duration == 25.0 - 2 * 0.3


def test_serializacao_roundtrip(tmp_path):
    plan = make_plan([Cut(1.5, 2.5, "silêncio")])
    plan.zooms = [ZoomEffect(5.0, 6.0, 0.2, "ênfase")]
    plan.transition_type = "slideleft"
    plan.source = "Claude (Anthropic)"

    path = plan.save(tmp_path / "plan.json")
    loaded = EditPlan.load(path)

    assert loaded.cuts == plan.cuts
    assert loaded.zooms == plan.zooms
    assert loaded.transition_type == "slideleft"
    assert loaded.source == "Claude (Anthropic)"


def test_validate_descarta_invalidos_e_mescla_sobrepostos():
    plan = EditPlan(
        cuts=[
            Cut(50, 60),  # ok
            Cut(55, 70, "sobreposto"),  # mescla com o anterior
            Cut(80, 80.1),  # curto demais
            Cut(120, 130),  # fora do vídeo
            Cut(10, 10),  # vazio
        ],
        zooms=[
            ZoomEffect(0, 1, 0.9),  # intensidade clampada p/ 0.4
            ZoomEffect(90, 91),  # curto demais
        ],
        transition_type="inexistente",
        duration=100.0,
    )
    plan = validate_plan(plan)
    assert len(plan.cuts) == 1
    assert plan.cuts[0].start == 50 and plan.cuts[0].end == 70
    assert plan.zooms[0].intensity == 0.4
    assert plan.transition_type == "fade"


def test_validate_descarta_zoom_sobreposto_a_corte():
    plan = EditPlan(
        cuts=[Cut(10, 20)],
        zooms=[ZoomEffect(12, 15), ZoomEffect(30, 32)],
        duration=100.0,
    )
    plan = validate_plan(plan)
    assert len(plan.zooms) == 1
    assert plan.zooms[0].start == 30


def test_snap_ajusta_corte_que_corta_palavra_no_meio():
    words = [
        Word("oi", 0.0, 0.5),
        Word("gente", 0.5, 1.0),
        Word("tudo", 2.0, 2.5),
        Word("bem", 2.5, 3.0),
    ]
    # corte de 0.7 a 2.3 cortaria "gente" (fim) e "tudo" (início)
    cuts = [Cut(0.7, 2.3)]
    snapped = snap_cuts_to_word_gaps(cuts, words)
    assert len(snapped) == 1
    assert snapped[0].start == 1.0  # puxado p/ fim de "gente"
    assert snapped[0].end == 2.0  # empurrado p/ início de "tudo"
