"""Palavras-chave em pop gigante (estilo anúncio).

Escolhe as palavras mais fortes da fala e gera uma camada ASS com o
efeito "pop 3D": a palavra estoura na tela com escala crescente
(overshoot + crescimento contínuo = sensação de profundidade), contorno
branco grosso e sombra — igual ao "animação" / "agora" do vídeo de
referência.

`pick_keywords` é pura e testável; `write_keywords_ass` só escreve texto.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from core.edit_plan import KeywordPop
from core.subtitle_engine import rgb_to_ass

logger = logging.getLogger(__name__)

MAX_KEYWORDS = 6  # teto por vídeo
MIN_GAP_S = 4.0  # mínimo entre um pop e outro
MIN_WORD_LEN = 4  # palavras muito curtas não chamam atenção
POP_DURATION_S = 1.5  # tempo em tela

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
    palavras mais longas ganham prioridade.
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


def write_keywords_ass(
    keywords: list[KeywordPop],
    out_path: Path,
    play_w: int,
    play_h: int,
) -> Path:
    """Camada ASS com o pop das palavras-chave (contorno branco + sombra)."""
    vertical = play_h >= play_w
    # palavra gigante no terço superior, como no anúncio
    font_size = int(play_w * (0.17 if vertical else 0.11))

    lines = [
        _HEADER.format(
            play_w=play_w,
            play_h=play_h,
            font_name="Anton",
            font_size=font_size,
            primary=rgb_to_ass("#FF6B2B"),
            outline=max(6, font_size // 14),
        )
    ]
    count = 0
    for kw in keywords:
        word = kw.word.strip().upper()
        if not word or kw.end <= kw.start:
            continue
        dur_ms = int((kw.end - kw.start) * 1000)
        grow_end = max(500, dur_ms - 250)
        # pop 3D: entra pequeno, estoura com overshoot e segue crescendo
        # devagar até o fim (sensação de aproximação da câmera)
        tags = (
            f"{{\\an5\\pos({play_w // 2},{int(play_h * 0.4)})"
            f"\\c{rgb_to_ass('#FF6B2B')}\\3c&HFFFFFF&\\4c&H000000&"
            f"\\fscx22\\fscy22"
            f"\\t(0,200,\\fscx116\\fscy116)"
            f"\\t(200,340,\\fscx100\\fscy100)"
            f"\\t(340,{grow_end},\\fscx112\\fscy112)"
            f"\\fad(60,220)}}"
        )
        lines.append(
            f"Dialogue: 30,{_fmt_time(kw.start)},{_fmt_time(kw.end)},"
            f"Keyword,,0,0,0,,{tags}{word}{{\\r}}"
        )
        count += 1

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Palavras-chave geradas: %s (%d pops)", out_path, count)
    return out_path
