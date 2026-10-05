"""Testes da detecção de cena e do alinhamento de cortes."""

from __future__ import annotations

from core.edit_plan import Cut, EditPlan, validate_plan
from core.scene_detect import align_cuts_to_scenes, parse_showinfo

SHOWINFO_SAMPLE = """
[frame:0 fps:0] pts_time:1.234
[frame:1 fps:0] pts_time:4.567
[frame:2 fps:0] pts_time:4.5675
[frame:3 fps:0] pts_time:9.0
"""


def test_parse_showinfo_extrai_tempos_e_deduplica():
    times = parse_showinfo(SHOWINFO_SAMPLE)
    assert times == [1.234, 4.567, 9.0]


def test_parse_showinfo_vazio():
    assert parse_showinfo("") == []


def test_align_snap_borda_para_cena():
    cuts = [Cut(start=1.0, end=1.5, reason="silêncio de 0.5s")]
    scenes = [1.15, 3.0]
    out = align_cuts_to_scenes(cuts, scenes, tolerance=0.4)
    # início encaixa na cena 1.15 (dentro da tolerância); fim não tem cena
    assert out[0].start == 1.15
    assert out[0].end == 1.5
    assert "mudança de cenário" in out[0].reason


def test_align_fora_da_tolerancia_nao_mexe():
    cuts = [Cut(start=1.0, end=1.5, reason="silêncio")]
    scenes = [2.5]
    out = align_cuts_to_scenes(cuts, scenes, tolerance=0.4)
    assert out[0].start == 1.0
    assert out[0].end == 1.5
    assert out[0].reason == "silêncio"


def test_align_nao_muta_entrada():
    c = Cut(start=1.0, end=1.5, reason="silêncio")
    align_cuts_to_scenes([c], [1.05], tolerance=0.4)
    assert c.start == 1.0


def test_align_mescla_colisao_criada_pelo_encaixe():
    cuts = [Cut(start=0.9, end=1.0), Cut(start=1.1, end=1.3)]
    scenes = [1.05]
    out = align_cuts_to_scenes(cuts, scenes, tolerance=0.4)
    # nenhum corte colapsa: fim do 1º estende até a cena, início do 2º
    # encaixa nela (tocando, sem inverter)
    assert len(out) == 2
    assert out[0].start == 0.9
    assert out[0].end == 1.05
    assert out[1].start == 1.05
    assert out[1].end == 1.3
    assert "mudança de cenário" in out[0].reason


def test_align_sem_cenas_devolve_iguais():
    cuts = [Cut(start=1.0, end=1.5)]
    out = align_cuts_to_scenes(cuts, [])
    assert out == cuts


def test_cut_preserva_transicao_no_alinhamento():
    cuts = [Cut(start=1.0, end=1.5, transition_type="dissolve", transition_duration=0.4)]
    out = align_cuts_to_scenes(cuts, [1.02], tolerance=0.4)
    assert out[0].transition_type == "dissolve"
    assert out[0].transition_duration == 0.4


def test_cut_transition_roundtrip():
    plan = EditPlan(
        cuts=[
            Cut(start=0.0, end=1.0, transition_type="slideleft", transition_duration=0.3),
            Cut(start=2.0, end=3.0),
        ],
        duration=5.0,
    )
    restored = EditPlan.from_dict(plan.to_dict())
    assert restored.cuts[0].transition_type == "slideleft"
    assert restored.cuts[0].transition_duration == 0.3
    assert restored.cuts[1].transition_type == ""


def test_validate_plan_descarta_transicao_desconhecida():
    plan = EditPlan(
        cuts=[Cut(start=0.0, end=1.0, transition_type="redemoinho", transition_duration=0.3)],
        duration=4.0,
    )
    plan = validate_plan(plan)
    assert plan.cuts[0].transition_type == ""
    assert plan.cuts[0].transition_duration == 0.0


def test_validate_plan_clampa_duracao_do_override():
    plan = EditPlan(
        cuts=[Cut(start=0.0, end=1.0, transition_type="fade", transition_duration=5.0)],
        duration=4.0,
    )
    plan = validate_plan(plan)
    assert plan.cuts[0].transition_duration == 1.0
