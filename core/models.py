"""Modelos de dados compartilhados entre os motores."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    """Uma palavra com timestamp preciso (segundos)."""

    text: str
    start: float
    end: float


@dataclass
class TranscriptChunk:
    """Grupo de palavras exibidas juntas na tela (estilo CapCut)."""

    words: list[Word] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.words[0].start if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1].end if self.words else 0.0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Transcript:
    """Transcrição completa, palavra a palavra."""

    words: list[Word] = field(default_factory=list)
    language: str = "pt"
    duration: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)
