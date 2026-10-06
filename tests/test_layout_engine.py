"""Testes do motor de cenas de layout (card + painel)."""

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
                 "title": "CONCEITO", "steps": ["A", "B"]}
            ],
            "duration": 20.0,
        }
        from core.edit_plan import EditPlan

        plan = EditPlan.from_dict(plan_dict)
        assert plan.layouts[0].side == "right"
        assert plan.layouts[0].steps == ["A", "B"]
        again = EditPlan.from_dict(plan.to_dict())
        assert again.layouts[0].title == "CONCEITO"
