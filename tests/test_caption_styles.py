from core.caption_styles import DEFAULT_STYLE, PRESETS, get_caption_style
from core.subtitle_engine import CaptionStyle


def test_preset_padrao_existe_e_e_valido():
    assert DEFAULT_STYLE in PRESETS
    assert isinstance(PRESETS[DEFAULT_STYLE], CaptionStyle)
    assert PRESETS[DEFAULT_STYLE].highlight_color == "#FFD400"
    assert PRESETS[DEFAULT_STYLE].uppercase is True


def test_retorna_preset_por_nome():
    style = get_caption_style("impacto_vermelho")
    assert style.highlight_color == "#FF3B30"


def test_nome_desconhecido_ou_vazio_cai_no_padrao():
    assert get_caption_style("nao_existe") is PRESETS[DEFAULT_STYLE]
    assert get_caption_style("") is PRESETS[DEFAULT_STYLE]
    assert get_caption_style(None) is PRESETS[DEFAULT_STYLE]


def test_presets_usam_fontes_embutidas():
    assert PRESETS["viral_amarelo"].font_name == "Anton"
    assert PRESETS["impacto_vermelho"].font_name == "Archivo Black"
    assert PRESETS["clean_ciano"].font_name == "Poppins ExtraBold"


def test_preset_padrao_tem_pop_e_impacto():
    style = PRESETS["viral_amarelo"]
    assert style.pop_animation is True
    assert style.active_scale >= 130
    assert style.outline >= 5
    assert style.shadow >= 2
