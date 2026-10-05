"""Testes do motor de palavras-chave (pop estilo anúncio)."""

from __future__ import annotations

from core.edit_plan import EditPlan, KeywordPop
from core.keyword_engine import pick_keywords, write_keywords_ass


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


def test_write_keywords_ass_gera_dialogos(tmp_path):
    kws = [
        KeywordPop(start=1.0, end=2.5, word="tecnologia"),
        KeywordPop(start=6.0, end=7.5, word="impacto"),
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


def test_write_keywords_ass_auto_ajuste_palavra_longa(tmp_path):
    curta = KeywordPop(start=1.0, end=2.5, word="casa")
    longa = KeywordPop(start=5.0, end=6.5, word="transformar")
    out = write_keywords_ass([curta, longa], tmp_path / "kw.ass", 1080, 1920)
    text = out.read_text(encoding="utf-8")
    import re

    scales = re.findall(r"\\blur8\\fscx(\d+)\\fscy", text)
    # escala inicial da palavra longa é menor que a da curta
    assert int(scales[0]) > int(scales[1])
    # e mesmo reduzida, a palavra longa cabe na largura do frame
    longa_line = next(
        line for line in text.splitlines() if "TRANSFORMAR" in line
    )
    final_scale = max(
        int(m)
        for m in re.findall(r"\\t\(\d+,\d+,\\fscx(\d+)", longa_line)
    )
    est_w = 11 * 0.56 * 183 * (final_scale / 100)
    assert est_w <= 1080 * 0.95


def test_write_keywords_ass_vazio(tmp_path):
    out = write_keywords_ass([], tmp_path / "kw.ass", 1080, 1920)
    assert "Dialogue:" not in out.read_text(encoding="utf-8")


def test_edit_plan_keywords_roundtrip():
    plan = EditPlan(
        keywords=[KeywordPop(start=1.0, end=2.5, word="tecnologia")],
        duration=10.0,
    )
    restored = EditPlan.from_dict(plan.to_dict())
    assert restored.keywords[0].word == "tecnologia"
    assert restored.keywords[0].start == 1.0
    assert restored.keywords[0].end == 2.5
