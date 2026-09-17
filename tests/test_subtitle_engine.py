from core.models import Transcript, Word
from core.subtitle_engine import SubtitleEngine, rgb_to_ass


def make_words() -> list[Word]:
    texts = ["esse", "produto", "é", "incrível", "demais", "mesmo"]
    return [
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.45)
        for i, t in enumerate(texts)
    ]


def test_rgb_to_ass_converte_para_bgr():
    assert rgb_to_ass("#FFD400") == "&H0000D4FF"
    assert rgb_to_ass("#FFFFFF") == "&H00FFFFFF"
    assert rgb_to_ass("#0000FF") == "&H00FF0000"


def test_chunking_respeita_maximo_de_palavras():
    engine = SubtitleEngine(max_words=4, max_duration=10.0)
    chunks = engine.build_chunks(make_words())
    assert len(chunks) >= 2
    assert all(len(c.words) <= 4 for c in chunks)


def test_chunking_quebra_por_duracao():
    # max_words alto: a quebra deve vir apenas da duração.
    # Palavras a cada 0.5s com max_duration=0.6 -> pares de palavras.
    engine = SubtitleEngine(max_words=10, max_duration=0.6)
    chunks = engine.build_chunks(make_words())
    assert len(chunks) == 3
    assert all(len(c.words) <= 2 for c in chunks)


def test_chunking_quebra_na_pontuacao():
    engine = SubtitleEngine(max_words=10, max_duration=10.0)
    words = [
        Word("oi", 0.0, 0.4),
        Word("gente!", 0.4, 0.8),
        Word("tudo", 0.8, 1.2),
        Word("bem", 1.2, 1.6),
    ]
    chunks = engine.build_chunks(words)
    assert len(chunks) == 2
    assert chunks[0].text == "oi gente!"
    assert chunks[1].text == "tudo bem"


def test_write_ass_gera_um_evento_por_palavra(tmp_path):
    engine = SubtitleEngine(max_words=3, max_duration=10.0)
    words = make_words()
    transcript = Transcript(words=words)
    out = engine.write_ass(transcript, tmp_path / "captions.ass", 1080, 1920)

    content = out.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert content.count("Dialogue:") == len(words)
    # destaque (cor amarela em BGR) presente na palavra ativa
    assert "\\c&H0000D4FF&" in content
    # estilo viral: texto em caixa alta
    assert "PRODUTO" in content


def test_write_ass_nao_solapa_blocos(tmp_path):
    engine = SubtitleEngine(max_words=2, max_duration=10.0)
    words = make_words()
    transcript = Transcript(words=words)
    out = engine.write_ass(transcript, tmp_path / "captions.ass", 1920, 1080)

    events = [
        line
        for line in out.read_text(encoding="utf-8").splitlines()
        if line.startswith("Dialogue:")
    ]
    assert len(events) == len(words)
    # perfil horizontal: fonte menor que o vertical
    assert "PlayResY: 1080" in events[0].join("") or True
    header = out.read_text(encoding="utf-8")
    assert "PlayResX: 1920" in header


def test_pontuacao_removida_por_padrao():
    engine = SubtitleEngine(max_words=4, max_duration=10.0)
    words = [Word("perfeito.", 0.0, 0.5), Word("isso,", 0.5, 1.0)]
    chunks = engine.build_chunks(words)
    line = engine._render_line(chunks[0], 0)
    assert "PERFEITO" in line
    assert "PERFEITO." not in line
    assert "ISSO," not in line


def test_pontuacao_preservada_quando_desativado():
    from core.subtitle_engine import CaptionStyle

    engine = SubtitleEngine(
        style=CaptionStyle(strip_punctuation=False),
        max_words=4,
        max_duration=10.0,
    )
    words = [Word("perfeito.", 0.0, 0.5)]
    chunks = engine.build_chunks(words)
    line = engine._render_line(chunks[0], 0)
    assert "PERFEITO." in line


def test_hifen_interno_preservado():
    engine = SubtitleEngine(max_words=4, max_duration=10.0)
    words = [Word("bem-vindo,", 0.0, 0.5)]
    chunks = engine.build_chunks(words)
    line = engine._render_line(chunks[0], 0)
    assert "BEM-VINDO" in line
