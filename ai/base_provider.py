"""Contrato padrão da camada de IA.

Qualquer provedor (Claude, GPT, Gemini, modelo local...) deve implementar
esta interface. O restante do programa depende apenas deste contrato —
trocar de provedor nunca exige reescrever motores ou UI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Optional

from ai.models import Callout, Highlight, MusicMood, TranscriptAnalysis


class AIProvider(ABC):
    """Interface única para provedores de IA de linguagem."""

    id: ClassVar[str] = "base"
    label: ClassVar[str] = "Provedor base"
    default_model: ClassVar[str] = ""
    requires_api_key: ClassVar[bool] = True
    env_key: ClassVar[str] = ""  # variável de ambiente usada como fallback

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.model = model or self.default_model

    @abstractmethod
    def analyze_transcript(
        self, transcript_text: str, language: str = "pt"
    ) -> TranscriptAnalysis:
        """Resume a transcrição e identifica tom e palavras-chave."""

    @abstractmethod
    def suggest_highlights(
        self,
        transcript_text: str,
        segments: Optional[list[dict]] = None,
        max_highlights: int = 5,
    ) -> list[Highlight]:
        """Sugere os melhores momentos (cortes/ênfases) do vídeo.

        `segments` é opcional e traz trechos com timestamps:
        [{"start": 0.0, "end": 3.2, "text": "..."}]
        """

    @abstractmethod
    def generate_caption_text(
        self, transcript_text: str, max_callouts: int = 5
    ) -> list[Callout]:
        """Gera textos de call-out (palavras-chave em destaque na tela)."""

    @abstractmethod
    def suggest_music_mood(self, transcript_text: str) -> MusicMood:
        """Sugere o clima/energia da música de fundo."""
