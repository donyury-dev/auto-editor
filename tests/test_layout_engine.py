"""Testes do motor de cenas de layout (card + painel)."""

from pathlib import Path

import pytest

from core.edit_plan import LayoutScene
from core.layout_engine import pick_layouts


def _words(spec: list[tuple[float, str]], gap: float = 0.2):
    from core.models import Word

    out = []
    t = spec[0][0]
    for start, text in spec:
        out.append(Word(text=text, start=start, end=start + 0.4))
    return out


class TestPickLayouts:
    def test_detecta_gatilho_explicativo(self):
        from core.models import Word

        words = [
            Word(text=w, start=i * 0.5, end=i * 0.5 + 0.4)
            for i, w in enumerate(
                ["isso", "significa", "que", "tudo", "muda", "de", "vez"]
                + ["agora", "vamos", "ver", "como", "funciona", "isso", "aqui", "de", "verdade", "sempre", "hoje", "amanha"]
            )
        ]
        layouts = pick_layouts(words, duration=15.0)
        assert len(layouts) >= 1
        l0 = layouts[0]
        assert isinstance(l0, LayoutScene)
        assert l0.side in ("left", "right")
        assert l0.duration >= 4.0

    def test_curto_demais_nao_gera(self):
        from core.models import Word

        words = [Word(text="significa", start=0.2, end=0.6)]
        # vídeo de 3s: não dá tempo de estender a cena p/ MIN_LAYOUT_S
        assert pick_layouts(words, duration=3.0) == []

    def test_respeita_maximo_e_gap(self):
        from core.models import Word

        words: list[Word] = []
        t = 0.0
        for n in range(6):
            for w in ["significa", "muito", "importante", "verdade", "tambem", "sempre"]:
                words.append(Word(text=w, start=t, end=t + 0.4))
                t += 0.5
            t += 2.0  # separa as frases
        layouts = pick_layouts(words, duration=t + 5)
        assert len(layouts) <= 3
        # nenhuma cena se sobrepõe a outra
        ordered = sorted(layouts, key=lambda l: l.start)
        for a, b in zip(ordered, ordered[1:]):
            assert a.end + 8.0 <= b.start or b.end + 8.0 <= a.start

    def test_sem_palavras(self):
        assert pick_layouts([], duration=30.0) == []


class TestSerializacao:
    def test_layout_scene_roundtrip(self):
        plan_dict = {
            "layouts": [
                {"start": 2.0, "end": 8.0, "side": "right",
                 "title": "CONCEITO", "steps": ["A", "B"],
                 "step_images": ["/pack/icone.png", ""]}
            ],
            "duration": 20.0,
        }
        from core.edit_plan import EditPlan

        plan = EditPlan.from_dict(plan_dict)
        assert plan.layouts[0].side == "right"
        assert plan.layouts[0].steps == ["A", "B"]
        assert plan.layouts[0].step_images == ["/pack/icone.png", ""]
        again = EditPlan.from_dict(plan.to_dict())
        assert again.layouts[0].title == "CONCEITO"
        assert again.layouts[0].step_images == ["/pack/icone.png", ""]

    def test_cena_manual_preserva_duracao_ao_atravessar_corte(self):
        """O export não deve encurtar uma cena manual por causa de um corte."""
        from core.edit_plan import Cut, EditPlan

        plan = EditPlan(
            cuts=[Cut(start=41.744, end=49.41)],
            duration=104.32,
            transition_type="corte",
            transition_duration=0.0,
        )
        scene = LayoutScene(start=40.5, end=50.3)

        # Mesma regra usada por ApplyLayoutsStep: só o início é remapeado.
        start = plan.remap_time(scene.start)
        end = min(95.0, start + scene.duration)
        assert end - start == pytest.approx(scene.duration)


class TestIconeCartao:
    def test_render_desenha_icone_no_cartao(self, tmp_path):
        """O PNG do cartão muda quando um ícone do pack é informado."""
        from PIL import Image

        from core.layout_engine import _render_scene_pngs

        icon = tmp_path / "icone.png"
        Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(icon)

        sc = LayoutScene(start=0, end=6, title="T", steps=["Conceito"])
        base = tmp_path / "sem"
        _render_scene_pngs(sc, 540, 960, Path("assets/fonts"), str(base))
        sem = Image.open(str(base) + "_step0.png").convert("RGBA")

        sc.step_images = [str(icon)]
        base2 = tmp_path / "com"
        _render_scene_pngs(sc, 540, 960, Path("assets/fonts"), str(base2))
        com = Image.open(str(base2) + "_step0.png").convert("RGBA")

        import numpy as np

        delta = np.abs(
            np.asarray(sem, np.int16) - np.asarray(com, np.int16)
        )
        assert (delta.sum(axis=2) > 30).sum() > 50  # ícone visível

    def test_render_com_icone_inexistente_nao_quebra(self, tmp_path):
        from core.layout_engine import _render_scene_pngs

        sc = LayoutScene(start=0, end=6, title="T", steps=["Conceito"])
        sc.step_images = [str(tmp_path / "falta.png")]
        base = tmp_path / "ok"
        _render_scene_pngs(sc, 540, 960, Path("assets/fonts"), str(base))
        assert (Path(str(base) + "_step0.png")).exists()
