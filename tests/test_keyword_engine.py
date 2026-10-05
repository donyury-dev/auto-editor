"""Testes do motor de palavras-chave (pop estilo anúncio)."""

from __future__ import annotations

from core.edit_plan import EditPlan, KeywordPop
from core.keyword_engine import EFFECT_STYLES, pick_keywords, write_keywords_ass


def W(text: str, start: float, end: float) -> dict:
    return {"text": text, "start": start, "end": end}


def test_pick_keywords_ignora_stopwords_e_curtas():
    words = [
        W("eu", 0.0, 0.2),
        W("de", 0.2, 0.3),
        W("tecnologia", 0.5, 1.2),
        W("mudou", 5.5, 6.0),
    ]
    kws = pick_keywords(words, duration=10.0)
    picked = [k.word for k in kws]
    assert "tecnologia" in picked
    assert "mudou" in picked
    assert all(k.word not in {"eu", "de"} for k in kws)


def test_pick_keywords_respeita_gap_minimo():
    words = [
        W("tecnologia", 0.5, 1.2),
        W("transformação", 2.0, 3.0),  # < 4s do anterior
        W("produtividade", 9.0, 10.0),
    ]
    kws = pick_keywords(words, duration=20.0)
    assert len(kws) == 2
    assert kws[1].start - kws[0].start >= 4.0


def test_pick_keywords_teto_e_dedupe():
    words = [W("tecnologia", i * 5.0, i * 5.0 + 0.5) for i in range(10)]
    kws = pick_keywords(words, duration=60.0)
    assert len(kws) <= 6
    words_lower = [k.word.lower() for k in kws]
    assert len(words_lower) == len(set(words_lower))


def test_pick_keywords_vazio():
    assert pick_keywords([], duration=10.0) == []
    assert pick_keywords([W("e", 0, 0.1), W("de", 0.2, 0.3)], duration=10.0) == []


def test_pick_keywords_ordena_por_tempo():
    words = [W("produtividade", 8.0, 9.0), W("tecnologia", 1.0, 2.0)]
    kws = pick_keywords(words, duration=20.0)
    assert [k.start for k in kws] == sorted(k.start for k in kws)


def test_pick_keywords_ciclo_de_efeitos():
    words = [
        W("tecnologia", 0.5, 1.2),
        W("transformar", 5.5, 6.2),
        W("produtividade", 10.5, 11.4),
        W("realidade", 15.5, 16.2),
        W("objetivos", 20.5, 21.2),
    ]
    kws = pick_keywords(words, duration=60.0)
    styles = [k.style for k in kws]
    assert styles == EFFECT_STYLES  # primeiro ciclo completo, sem repetir


def test_write_keywords_ass_travessia(tmp_path):
    kws = [
        KeywordPop(start=1.0, end=2.5, word="tecnologia", style="travessia"),
        KeywordPop(start=6.0, end=7.5, word="impacto", style="travessia"),
    ]
    out = write_keywords_ass(kws, tmp_path / "kw.ass", 1080, 1920)
    text = out.read_text(encoding="utf-8")
    assert text.count("Dialogue: 30,") == 2
    assert "TECNOLOGIA" in text
    assert "IMPACTO" in text
    # contorno branco + sombra + travessia (move/blur/escala)
    assert "\\3c&HFFFFFF&" in text
    assert "\\move(" in text
    assert "\\blur8" in text
    assert "\\fad(80,220)" in text


def test_write_keywords_ass_estilos_variados(tmp_path):
    kws = [
        KeywordPop(start=1.0, end=2.5, word="agora", style="grifo"),
        KeywordPop(start=6.0, end=7.5, word="erro", style="impacto"),
        KeywordPop(start=11.0, end=12.5, word="vamos", style="tremor"),
        KeywordPop(start=16.0, end=17.5, word="mudo", style="quebra"),
    ]
    out = write_keywords_ass(kws, tmp_path / "kw.ass", 1080, 1920)
    text = out.read_text(encoding="utf-8")
    # grifo: barra = palavra achatada em laranja por baixo do texto branco
    assert "\\fscy8" in text
    assert "&HFFFFFF&" in text
    # impacto: vermelho + slam (escala inicial grande, mas assenta ≤106%)
    assert "2b39e6" in text.lower()  # vermelho em BGR (formato ASS)
    assert "\\fscx190" in text
    assert "\\fscx310" not in text  # slam antigo estourava o frame
    # tremor: rotação oscilante
    assert "\\frz3" in text
    # quebra: karaoke por letra
    assert "\\k1" in text or "\\k2" in text or "\\k3" in text
    # posição acima da cabeça (20% da altura), não no rosto
    assert f"\\pos(540,{int(1920 * 0.20)})" in text


def test_write_keywords_ass_auto_ajuste_palavra_longa(tmp_path):
    curta = KeywordPop(start=1.0, end=2.5, word="casa", style="travessia")
    longa = KeywordPop(
        start=5.0, end=6.5, word="transformar", style="travessia"
    )
    out = write_keywords_ass([curta, longa], tmp_path / "kw.ass", 1080, 1920)
    text = out.read_text(encoding="utf-8")
    import re

    longa_line = next(
        line for line in text.splitlines() if "TRANSFORMAR" in line
    )
    curta_line = next(line for line in text.splitlines() if "CASA" in line)
    fs_longa = int(re.search(r"\\fs(\d+)", longa_line).group(1))
    fs_curta = int(re.search(r"\\fs(\d+)", curta_line).group(1))
    assert fs_longa < fs_curta  # palavra longa recebe fonte menor
    # largura da longa no crescimento máximo (110%) cabe no frame,
    # respeitando a folga real da travessia (anda ±2% da largura)
    from core.keyword_engine import _measure_text

    max_w = _measure_text("TRANSFORMAR", fs_longa) * 1.10
    assert max_w <= 1080 * 0.96 - 40


def test_write_keywords_ass_vazio(tmp_path):
    out = write_keywords_ass([], tmp_path / "kw.ass", 1080, 1920)
    assert "Dialogue:" not in out.read_text(encoding="utf-8")


def test_edit_plan_keywords_roundtrip():
    plan = EditPlan(
        keywords=[
            KeywordPop(start=1.0, end=2.5, word="tecnologia", style="grifo")
        ],
        duration=10.0,
    )
    restored = EditPlan.from_dict(plan.to_dict())
    assert restored.keywords[0].word == "tecnologia"
    assert restored.keywords[0].start == 1.0
    assert restored.keywords[0].end == 2.5
    assert restored.keywords[0].style == "grifo"
