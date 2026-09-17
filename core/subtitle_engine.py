"""Motor de legendas estilo viral (CapCut/Opus Clip/Submagic).

Gera um arquivo ASS com sincronização palavra a palavra: cada "tela" mostra
um grupo de palavras e a palavra ativa é destacada com cor + leve zoom.
"""

from __future__ import annotations

import logging
import string
from dataclasses import dataclass
from pathlib import Path

from core.models import Transcript, TranscriptChunk, Word

logger = logging.getLogger(__name__)

# Pontuação removida das pontas das palavras quando strip_punctuation=True
# (hífen/apóstrofo internos, ex. "bem-vindo", são preservados).
_STRIP_CHARS = string.punctuation + "«»“”‘’…—–"


@dataclass
class CaptionStyle:
    """Estilo visual das legendas."""

    font_name: str = "Anton"
    font_size_vertical: int = 74
    font_size_horizontal: int = 58
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFD400"
    outline: int = 5
    shadow: int = 2
    margin_v_vertical: int = 420
    margin_v_horizontal: int = 150
    uppercase: bool = True
    active_scale: int = 135
    strip_punctuation: bool = True
    # Animação de "pop" da palavra ativa: cresce de 0 até o alvo passando
    # por um pico (overshoot) e assenta — efeito bounce estilo CapCut.
    pop_animation: bool = True
    pop_overshoot: int = 10  # % acima do escala final no pico do bounce
    pop_duration_ms: int = 140
    # Glow suave na palavra ativa (0 = desligado; ~0.5-1.0 = sutil)
    active_glow: float = 0.0


def rgb_to_ass(hex_color: str) -> str:
    """Converte '#RRGGBB' para a notação de cor do ASS ('&HAABBGGRR')."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b.upper()}{g.upper()}{r.upper()}"


def _fmt_time(seconds: float) -> str:
    """Formata segundos como 'h:mm:ss.cc' (timestamp do ASS)."""
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    hours, rem = divmod(cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Viral,{font_name},{font_size},{primary},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


class SubtitleEngine:
    """Agrupa palavras em blocos e gera o arquivo ASS estilo viral."""

    def __init__(
        self,
        style: CaptionStyle | None = None,
        max_words: int = 4,
        max_duration: float = 2.5,
    ) -> None:
        self.style = style or CaptionStyle()
        self.max_words = max(1, max_words)
        self.max_duration = max(0.5, max_duration)

    def build_chunks(self, words: list[Word]) -> list[TranscriptChunk]:
        """Agrupa palavras por quantidade, duração máxima e pontuação."""
        chunks: list[TranscriptChunk] = []
        current: list[Word] = []
        for word in words:
            current.append(word)
            text = word.text.rstrip()
            ends_sentence = bool(text) and text[-1] in ".!?"
            duration = current[-1].end - current[0].start
            if (
                ends_sentence
                or len(current) >= self.max_words
                or duration >= self.max_duration
            ):
                chunks.append(TranscriptChunk(words=current))
                current = []
        if current:
            chunks.append(TranscriptChunk(words=current))
        return chunks

    def _render_line(self, chunk: TranscriptChunk, active_idx: int) -> str:
        """Monta a linha ASS com a palavra ativa destacada (cor + zoom)."""
        style = self.style
        highlight = rgb_to_ass(style.highlight_color)
        parts: list[str] = []
        for i, word in enumerate(chunk.words):
            text = word.text.strip().replace("{", "").replace("}", "")
            if style.strip_punctuation:
                stripped = text.strip(_STRIP_CHARS)
                text = stripped or text
            if style.uppercase:
                text = text.upper()
            if i == active_idx:
                parts.append(self._render_active(text, highlight))
            else:
                parts.append(text)
        return " ".join(parts)

    def _render_active(self, text: str, highlight: str) -> str:
        """Marca a palavra ativa: cor de destaque + pop com bounce."""
        style = self.style
        scale = max(100, style.active_scale)
        glow = (
            f"\\blur{style.active_glow}" if style.active_glow > 0 else ""
        )
        if not style.pop_animation:
            return (
                f"{{\\c{highlight}&{glow}\\fscx{scale}"
                f"\\fscy{scale}}}{text}{{\\r}}"
            )
        # Bounce: 0% -> pico (escala + overshoot) -> escala final.
        peak = min(200, scale + style.pop_overshoot)
        t1 = int(style.pop_duration_ms * 0.45)
        t2 = style.pop_duration_ms
        return (
            f"{{\\c{highlight}&{glow}\\fscx0\\fscy0"
            f"\\t(0,{t1},\\fscx{peak}\\fscy{peak})"
            f"\\t({t1},{t2},\\fscx{scale}\\fscy{scale})}}{text}{{\\r}}"
        )

    def write_ass(
        self,
        transcript: Transcript,
        out_path: Path,
        play_w: int,
        play_h: int,
    ) -> Path:
        """Gera o arquivo .ass completo para a resolução de saída indicada."""
        style = self.style
        vertical = play_h >= play_w
        header = _ASS_HEADER.format(
            play_w=play_w,
            play_h=play_h,
            font_name=style.font_name,
            font_size=(
                style.font_size_vertical
                if vertical
                else style.font_size_horizontal
            ),
            primary=rgb_to_ass(style.primary_color),
            outline=style.outline,
            shadow=style.shadow,
            margin_v=(
                style.margin_v_vertical
                if vertical
                else style.margin_v_horizontal
            ),
        )

        chunks = self.build_chunks(transcript.words)
        lines = [header]
        for ci, chunk in enumerate(chunks):
            next_start = (
                chunks[ci + 1].words[0].start
                if ci + 1 < len(chunks)
                else chunk.end + 1.0
            )
            chunk_end = min(chunk.end + 0.15, next_start - 0.01)
            for ki, word in enumerate(chunk.words):
                start = word.start
                end = (
                    chunk.words[ki + 1].start
                    if ki + 1 < len(chunk.words)
                    else chunk_end
                )
                end = max(end, start + 0.05)
                line = self._render_line(chunk, ki)
                lines.append(
                    f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end)},"
                    f"Viral,,0,0,0,,{line}"
                )

        out_path = Path(out_path)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info("Legendas geradas: %s (%d blocos)", out_path, len(chunks))
        return out_path
