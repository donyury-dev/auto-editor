"""Testes do dedupe call-out × palavra-chave (sem texto duplicado na tela)."""

from core.illustration_plan import (
    IllustrationMoment,
    dedupe_callouts_vs_keywords,
)
from core.edit_plan import KeywordPop


def kw(word, start, end):
    return KeywordPop(start=start, end=end, word=word)


def co(text, start, end):
    return IllustrationMoment(
        start=start, end=end, text=text, kind="callout", callout_text=text
    )


def test_callout_duplicado_de_keyword_e_removido():
    # IA sugeriu call-out "TECNOLOGIA" e o motor criou pop "tecnologia"
    # na mesma fala → só o pop fica.
    moments = [
        co("TECNOLOGIA", 3.2, 5.9),
        co("1 CLIQUE", 39.8, 40.9),  # sem keyword: permanece
    ]
    keywords = [kw("tecnologia", 3.7, 5.2)]
    out = dedupe_callouts_vs_keywords(moments, keywords)
    assert [m.callout_text for m in out] == ["1 CLIQUE"]


def test_acento_e_caixa_nao_impedem_dedupe():
    moments = [co("INTELIGÊNCIA ARTIFICIAL", 64.0, 66.0)]
    keywords = [kw("inteligência", 64.5, 65.8)]
    out = dedupe_callouts_vs_keywords(moments, keywords)
    assert out == []


def test_callout_fora_do_tempo_da_keyword_permanece():
    moments = [co("tecnologia", 50.0, 52.0)]
    keywords = [kw("tecnologia", 3.7, 5.2)]  # outro momento do vídeo
    out = dedupe_callouts_vs_keywords(moments, keywords)
    assert len(out) == 1


def test_imagens_nunca_sao_removidas():
    moments = [
        IllustrationMoment(
            start=3.2, end=5.9, text="TECNOLOGIA", kind="image",
            callout_text="TECNOLOGIA", image_path="/tmp/x.png",
        )
    ]
    keywords = [kw("tecnologia", 3.7, 5.2)]
    out = dedupe_callouts_vs_keywords(moments, keywords)
    assert len(out) == 1
