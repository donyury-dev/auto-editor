"""Modelos de dados trocados com os provedores de IA."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TranscriptAnalysis:
    summary: str = ""
    tone: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class Highlight:
    text: str
    start: float = 0.0
    end: float = 0.0
    reason: str = ""
    score: float = 0.0


@dataclass
class Callout:
    text: str
    emphasis: str = "alta"


@dataclass
class MusicMood:
    mood: str = "energético"
    energy: float = 0.7
    keywords: list[str] = field(default_factory=list)
    suggested_bpm: int = 120
