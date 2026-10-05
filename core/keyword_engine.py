"""Palavras-chave em pop gigante (estilo anúncio).

Escolhe as palavras mais fortes da fala e gera uma camada ASS com
efeitos variados, como no vídeo de referência:

- travessia: surge pequena/embaçada e atravessa a cena crescendo (3D)
- quebra: as letras aparecem uma a uma, mudando de cor (karaoke \kf)
- grifo: palavra branca com marca-texto laranja desenhado por baixo
- tremor: palavra que treme/pulsa depois de entrar
- impacto: palavra vermelha que desaba na tela (slam)

O tamanho é medido com a fonte Anton real (PIL) e reduzido por palavra
pra nunca estourar a largura do frame.

`pick_keywords` é pura e testável; `write_keywords_ass` só escreve texto.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.edit_plan import KeywordPop
from core.subtitle_engine import rgb_to_ass

logger = logging.getLogger(__name__)

MAX_KEYWORDS = 6  # teto por vídeo
MIN_GAP_S = 4.0  # mínimo entre um pop e outro
MIN_WORD_LEN = 4  # palavras muito curtas não chamam atenção
POP_DURATION_S = 1.5  # tempo em tela

# efeitos disponíveis ("" no keyword = ciclo automático)
EFFECT_STYLES = ["travessia", "quebra", "grifo", "tremor", "impacto"]

_FONT_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Anton-Regular.ttf"
)
_font_cache: dict[int, object] = {}


def _measure_text(text: str, size: int) -> float:
    """Largura exata do texto na Anton (PIL). Fallback: estimativa."""
    try:
        from PIL import ImageFont

        font = _font_cache.get(size)
        if font is None:
            font = ImageFont.truetype(str(_FONT_PATH), size)
            _font_cache[size] = font
        return float(font.getlength(text))
    except Exception:  # pragma: no cover - fallback sem PIL/fonte
        return len(text) * 0.66 * size


# palavras funcionais em português que não rendem destaque
STOPWORDS_PT = {
    "a", "à", "ao", "aos", "aquela", "aquele", "aquilo", "as", "às", "assim",
    "até", "com", "como", "da", "dá", "das", "de", "dele", "dela", "deles",
    "delas", "desde", "dessa", "desse", "disso", "do", "dos", "e", "ela",
    "ele", "elas", "eles", "em", "essa", "esse", "esto", "eu", "isso", "já",
    "la", "lhe", "lhes", "mais", "mas", "me", "meu", "meus", "mim", "muito",
    "na", "ná", "nada", "nas", "nem", "no", "nos", "nós", "o", "os", "ou",
    "para", "pra", "pelo", "pelos", "por", "porque", "que", "quem", "se",
    "sem", "ser", "seu", "seus", "só", "sua", "suas", "também", "te", "tem",
    "tém", "um", "uma", "você", "vocês", "voce",
}

_WORD_RE = re.compile(r"^[a-záàâãéêíóôõúüç]+$", re.IGNORECASE)


def _is_strong(word: str) -> bool:
    w = word.strip().strip(".,!?…—-").lower()
    if len(w) < MIN_WORD_LEN or w in STOPWORDS_PT:
        return False
    if not _WORD_RE.match(w):
        return False
    return True


def pick_keywords(
    words: list,
    duration: float,
    max_count: int = MAX_KEYWORDS,
    min_gap_s: float = MIN_GAP_S,
) -> list[KeywordPop]:
    """Escolhe as palavras-chave da transcrição (pura).

    `words` são objetos/dicts com start/end/text (palavras do Whisper).
    Critérios: palavra forte (não-stopword, tamanho mínimo), espaçadas
    pelo vídeo (sem amontoar pops), primeira ocorrência de cada palavra e
    palavras mais longas ganham prioridade. Efeitos variados ciclo entre
    os estilos (cada pop tem uma cara, como no anúncio).
    """
    if not words:
        return []

    def get(w, key, default=0.0):
        return float(w[key]) if isinstance(w, dict) else float(getattr(w, key, default))

    candidates: list[tuple[float, float, str]] = []
    for w in words:
        text = str(w["text"] if isinstance(w, dict) else getattr(w, "text", ""))
        token = text.strip().strip(".,!?…—-")
        if not _is_strong(token):
            continue
        candidates.append((get(w, "start"), get(w, "end"), token))

    # primeira ocorrência de cada palavra (normalizada em minúsculas)
    seen: set[str] = set()
    unique: list[tuple[float, float, str]] = []
    for s, e, tok in candidates:
        key = tok.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((s, e, tok))

    # mais longas primeiro (mais "impactantes"), depois espaça no tempo
    unique.sort(key=lambda x: (-len(x[2]), x[0]))
    chosen: list[KeywordPop] = []
    for s, e, tok in unique:
        if len(chosen) >= max_count:
            break
        if any(abs(s - c.start) < min_gap_s for c in chosen):
            continue
        start = max(0.0, s - 0.1)
        end = min(duration, start + POP_DURATION_S) if duration > 0 else start + POP_DURATION_S
        if end - start < 0.4:
            continue
        chosen.append(KeywordPop(start=start, end=end, word=tok))

    chosen.sort(key=lambda k: k.start)
    for i, kw in enumerate(chosen):
        if not kw.style:
            kw.style = EFFECT_STYLES[i % len(EFFECT_STYLES)]
    return chosen


def _fmt_time(seconds: float) -> str:
    centiseconds = int(round(max(0.0, seconds) * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Keyword,{font_name},{font_size},{primary},&H00FFFFFF,&H00FFFFFF,&HA0000000,-1,0,0,0,100,100,0,0,1,{outline},6,5,100,100,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ORANGE = rgb_to_ass("#FF6B2B")
WHITE = "&HFFFFFF&"
DARK = "&H1A1A1A&"
RED = rgb_to_ass("#E6392B")


def _fit_size(word: str, base_size: int, usable_w: float, grow: float) -> int:
    """Maior tamanho de fonte em que a palavra cabe (com folga de growth)."""
    size = base_size
    while size > base_size // 3 and _measure_text(word, size) * grow > usable_w:
        size = int(size * 0.92)
    return size


def _event_travessia(kw: KeywordPop, word: str, size: int, play_w: int, play_h: int) -> str:
    """Surge pequena/embaçada e atravessa a cena crescendo (profundidade)."""
    dur_ms = int((kw.end - kw.start) * 1000)
    grow_end = max(500, dur_ms - 250)
    cy = int(play_h * 0.4)
    sx, ex = int(play_w * 0.56), int(play_w * 0.44)
    tags = (
        f"{{\\an5\\fs{size}\\move({sx},{cy},{ex},{cy},0,{dur_ms})"
        f"\\c{ORANGE}\\3c{WHITE}\\4c&H000000&"
        f"\\blur8\\fscx20\\fscy20"
        f"\\t(0,{int(dur_ms * 0.22)},\\fscx105\\fscy105\\blur1.2)"
        f"\\t({int(dur_ms * 0.22)},{int(dur_ms * 0.3)},"
        f"\\fscx100\\fscy100\\blur0)"
        f"\\t({int(dur_ms * 0.3)},{grow_end},\\fscx118\\fscy118)"
        f"\\fad(80,220)}}"
    )
    return tags


def _event_quebra(kw: KeywordPop, word: str, size: int, play_w: int, play_h: int) -> str:
    """Letras aparecem uma a uma, mudando de cor (karaoke)."""
    dur_ms = int((kw.end - kw.start) * 1000)
    sweep_ms = min(900, int(dur_ms * 0.55))
    per_letter = max(1, sweep_ms // max(1, len(word)) // 10)  # centissegundos
    kar = "".join(f"\\k{per_letter}" for _ in word)
    cy = int(play_h * 0.4)
    tags = (
        f"{{\\an5\\fs{size}\\pos({play_w // 2},{cy})"
        f"\\1c{ORANGE}\\2c{WHITE}\\3c{DARK}\\4c&H000000&"
        f"{kar}"
        f"\\fscx30\\fscy30\\t(0,180,\\fscx108\\fscy108)"
        f"\\t(180,280,\\fscx100\\fscy100)"
        f"\\fad(50,200)}}"
    )
    return tags


def _event_grifo(kw: KeywordPop, word: str, size: int, play_w: int, play_h: int) -> str:
    """Palavra branca com marca-texto laranja desenhado por baixo.

    A barra é a própria palavra achatada (fscy baixo) em laranja — assim
    ela acompanha a largura exata do texto em qualquer tamanho de fonte.
    """
    dur_ms = int((kw.end - kw.start) * 1000)
    cy = int(play_h * 0.4)
    bar_h = max(6, int(size * 0.07))
    # barra (layer 20, atrás do texto): cresce como um grifo de caneta
    bar = (
        f"Dialogue: 20,{_fmt_time(kw.start + 0.12)},{_fmt_time(kw.end)},"
        f"Keyword,,0,0,0,,{{\\an5\\fs{size}"
        f"\\pos({play_w // 2},{cy + int(size * 0.40)})"
        f"\\1c{ORANGE}\\3c{ORANGE}\\bord{bar_h}"
        f"\\fscx0\\fscy8"
        f"\\t(0,{min(420, dur_ms // 3)},\\fscx100)\\fad(0,150)}}"
        f"{word}{{\\r}}"
    )
    text = (
        f"{{\\an5\\fs{size}\\pos({play_w // 2},{cy})"
        f"\\1c{WHITE}\\3c{DARK}\\4c&H000000&"
        f"\\fscx40\\fscy40\\t(0,160,\\fscx104\\fscy104)"
        f"\\t(160,260,\\fscx100\\fscy100)\\fad(40,180)}}"
    )
    return bar + "\n" + f"Dialogue: 30,{_fmt_time(kw.start)},{_fmt_time(kw.end)},Keyword,,0,0,0,,{text}{word}{{\\r}}"


def _event_tremor(kw: KeywordPop, word: str, size: int, play_w: int, play_h: int) -> str:
    """Palavra branca que entra e depois treme/pulsa."""
    dur_ms = int((kw.end - kw.start) * 1000)
    shake_ms = max(400, dur_ms - 350)
    step = 110
    shake = ""
    t = 0
    signs = [3, -3, 2, -2, 3, -1]
    i = 0
    while t < shake_ms:
        end = min(t + step, shake_ms)
        shake += f"\\t({t},{end},\\frz{signs[i % len(signs)]}\\fscy{102 if i % 2 else 98})"
        t += step
        i += 1
    cy = int(play_h * 0.4)
    tags = (
        f"{{\\an5\\fs{size}\\pos({play_w // 2},{cy})"
        f"\\1c{WHITE}\\3c{DARK}\\4c&H000000&"
        f"\\fscx20\\fscy20\\t(0,200,\\fscx112\\fscy112)"
        f"\\t(200,300,\\fscx100\\fscy100){shake}"
        f"\\fad(60,200)}}"
    )
    return tags


def _event_impacto(kw: KeywordPop, word: str, size: int, play_w: int, play_h: int) -> str:
    """Palavra vermelha que desaba na tela (slam)."""
    cy = int(play_h * 0.4)
    dur_ms = int((kw.end - kw.start) * 1000)
    tags = (
        f"{{\\an5\\fs{size}\\pos({play_w // 2},{cy})"
        f"\\1c{RED}\\3c{WHITE}\\4c&H000000&"
        f"\\fscx310\\fscy310\\blur6"
        f"\\t(0,140,\\fscx96\\fscy96\\blur0)"
        f"\\t(140,240,\\fscx104\\fscy104)"
        f"\\t(240,340,\\fscx100\\fscy100)"
        f"\\t(340,{max(500, dur_ms - 300)},\\fscx106\\fscy106)"
        f"\\fad(0,220)}}"
    )
    return tags


_EVENTS = {
    "travessia": _event_travessia,
    "quebra": _event_quebra,
    "grifo": _event_grifo,
    "tremor": _event_tremor,
    "impacto": _event_impacto,
}


def write_keywords_ass(
    keywords: list[KeywordPop],
    out_path: Path,
    play_w: int,
    play_h: int,
) -> Path:
    """Camada ASS com os pops das palavras-chave (efeitos variados)."""
    vertical = play_h >= play_w
    base_size = int(play_w * (0.17 if vertical else 0.11))
    usable_w = play_w * 0.92

    lines = [
        _HEADER.format(
            play_w=play_w,
            play_h=play_h,
            font_name="Anton",
            font_size=base_size,
            primary=ORANGE,
            outline=max(6, base_size // 14),
        )
    ]
    count = 0
    for kw in keywords:
        word = kw.word.strip().upper()
        if not word or kw.end <= kw.start:
            continue
        style = kw.style if kw.style in _EVENTS else "travessia"
        # auto-ajuste com a fonte real: cada efeito tem um fator de growth
        grow = 1.18 if style in ("travessia", "impacto", "tremor") else 1.0
        size = _fit_size(word, base_size, usable_w, grow)
        if style == "grifo":
            lines.append(_event_grifo(kw, word, size, play_w, play_h))
        else:
            tags = _EVENTS[style](kw, word, size, play_w, play_h)
            lines.append(
                f"Dialogue: 30,{_fmt_time(kw.start)},{_fmt_time(kw.end)},"
                f"Keyword,,0,0,0,,{tags}{word}{{\\r}}"
            )
        count += 1

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Palavras-chave geradas: %s (%d pops)", out_path, count)
    return out_path
