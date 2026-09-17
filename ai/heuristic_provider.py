"""Provedor heurístico local — não exige API key nem rede.

Gera um plano de edição determinístico a partir da transcrição:
- cortes nos silêncios (gaps entre palavras)
- zooms nas palavras mais "carregadas" (mais longas = mais enfatizadas)
- transições do tipo fade nos pontos de corte

Usado como fallback quando o provedor de IA ativo não está configurado.
"""

from __future__ import annotations

import logging

from ai.base_provider import AIProvider
from ai.models import Callout, Highlight, MusicMood, TranscriptAnalysis
from core.edit_plan import MIN_CUT_S, ZOOM_MIN_DURATION_S

logger = logging.getLogger(__name__)

SILENCE_GAP_S = 0.7  # gaps >= isso viram sugestão de corte
MAX_ZOOMS = 4
MIN_WORD_S = 0.45  # palavra precisa durar isso pra virar zoom
ZOOM_SPREAD_S = 6.0  # distância mínima entre zooms (garante voltar a 100%)
ZOOM_INTENSITY = 0.10  # 10% de zoom no pico (mais conservador)
ZOOM_PAD_BEFORE_S = 0.15
ZOOM_PAD_AFTER_S = 0.6


class HeuristicProvider(AIProvider):
    id = "heuristico"
    label = "Heurística local (sem IA)"
    default_model = ""
    requires_api_key = False

    # ------------------------------------------------------------------
    # Contrato AIProvider — decisões simples, sem rede
    # ------------------------------------------------------------------

    def analyze_transcript(
        self, transcript_text: str, language: str = "pt"
    ) -> TranscriptAnalysis:
        words = transcript_text.split()
        return TranscriptAnalysis(
            summary=f"{len(words)} palavras transcritas.",
            tone="direto",
            keywords=[w.lower().strip(".,!?;:") for w in words[:5]],
        )

    def suggest_highlights(
        self, transcript_text, segments=None, max_highlights=5
    ):
        return []

    def generate_caption_text(self, transcript_text, max_callouts=5):
        return []

    def suggest_music_mood(self, transcript_text) -> MusicMood:
        return MusicMood(mood="neutro", energy=0.5)

    def suggest_edit_plan(
        self,
        transcript_text: str,
        segments: list[dict],
        duration: float,
        language: str = "pt",
    ) -> dict:
        words = [s for s in segments if s.get("text", "").strip()]

        # cortes: silêncios entre palavras (e silêncio final)
        cuts = []
        for i in range(1, len(words)):
            gap = float(words[i]["start"]) - float(words[i - 1]["end"])
            if gap >= SILENCE_GAP_S:
                cuts.append(
                    {
                        "start": float(words[i - 1]["end"]),
                        "end": float(words[i]["start"]),
                        "reason": f"silêncio de {gap:.1f}s",
                    }
                )
        if words and duration - float(words[-1]["end"]) >= SILENCE_GAP_S:
            cuts.append(
                {
                    "start": float(words[-1]["end"]),
                    "end": duration,
                    "reason": "silêncio no final",
                }
            )

        # zooms: palavras mais longas (ênfase), espaçadas entre si
        candidates = sorted(
            [
                w
                for w in words
                if float(w["end"]) - float(w["start"]) >= MIN_WORD_S
            ],
            key=lambda w: float(w["end"]) - float(w["start"]),
            reverse=True,
        )[: MAX_ZOOMS * 3]
        zooms = []
        for w in candidates:
            if len(zooms) >= MAX_ZOOMS:
                break
            start = max(0.0, float(w["start"]) - ZOOM_PAD_BEFORE_S)
            end = min(duration, float(w["end"]) + ZOOM_PAD_AFTER_S)
            # garante duração mínima para o movimento ser perceptível
            if end - start < ZOOM_MIN_DURATION_S:
                center = (start + end) / 2
                start = max(0.0, center - ZOOM_MIN_DURATION_S / 2)
                end = min(duration, center + ZOOM_MIN_DURATION_S / 2)
            if any(abs(z["start"] - start) < ZOOM_SPREAD_S for z in zooms):
                continue
            zooms.append(
                {
                    "start": start,
                    "end": end,
                    "intensity": ZOOM_INTENSITY,
                    "reason": (
                        f"ênfase em “{w['text'].strip('.,!?;:')}”"
                    ),
                }
            )

        return {
            "cuts": cuts,
            "zooms": zooms,
            "transition_type": "corte",  # talking head fica mais natural com corte seco
            "transition_duration": 0.1,
        }
