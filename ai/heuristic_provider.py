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

# Ilustrações: gatilhos explícitos (heurística conservadora, sem IA)
ILLUSTRATION_TRIGGERS = (
    "imagina",
    "imaginem",
    "imaginando",
    "pensa",
    "pense",
    "suponha",
    "suponhamos",
    "exemplo",
)
ILLUSTRATION_MAX_WORDS = 4  # palavras capturadas após o gatilho
ILLUSTRATION_MIN_S = 1.5
ILLUSTRATION_MAX_S = 4.0
ILLUSTRATION_FILLER = {
    "que", "um", "uma", "uns", "umas", "o", "a", "os", "as",
    "de", "do", "da", "com", "em", "no", "na", "pra", "para", "e",
    "num", "numa", "pro",
}


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

    def suggest_music_mood(
        self, transcript_text: str, segments=None
    ) -> MusicMood:
        """Clima estimado pelo ritmo da fala (palavras por segundo)."""
        if segments:
            words = [s for s in segments if s.get("text", "").strip()]
            duration = max(
                0.1,
                float(words[-1]["end"]) - float(words[0]["start"])
                if words
                else 0.1,
            )
            rate = len(words) / duration
            if rate >= 2.8:
                return MusicMood(mood="energético", energy=0.8, suggested_bpm=128)
            if rate >= 2.0:
                return MusicMood(mood="motivacional", energy=0.6, suggested_bpm=110)
            return MusicMood(mood="calmo", energy=0.4, suggested_bpm=90)
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

    def suggest_illustration_moments(
        self,
        transcript_text: str,
        segments: list[dict],
        duration: float,
        language: str = "pt",
        density_s: float = 8.0,
    ) -> list[dict]:
        """Heurística conservadora: só gatilhos explícitos viram imagem.

        Ex.: "imagina uma casa na praia" → momento cobrindo a frase, com
        prompt "casa na praia" (palavras de conteúdo, sem conectores).
        """
        words = [
            s
            for s in segments
            if s.get("text", "").strip()
        ]
        moments: list[dict] = []
        last_start = -1e9

        i = 0
        while i < len(words):
            token = (
                words[i]["text"].lower().strip(".,!?;:")
            )
            is_trigger = any(
                token == t or token.startswith(t) for t in ILLUSTRATION_TRIGGERS
            )
            if not is_trigger:
                i += 1
                continue

            trigger_start = float(words[i]["start"])
            if trigger_start - last_start < density_s:
                i += 1
                continue

            # captura até ILLUSTRATION_MAX_WORDS palavras de conteúdo
            content: list[str] = []
            j = i + 1
            while j < len(words) and len(content) < ILLUSTRATION_MAX_WORDS:
                w = words[j]["text"].strip(".,!?;:")
                lw = w.lower()
                if lw in ILLUSTRATION_FILLER:
                    j += 1
                    continue
                if float(words[j]["start"]) - trigger_start > ILLUSTRATION_MAX_S:
                    break
                content.append(w)
                j += 1

            if content:
                start = trigger_start
                end = min(
                    float(words[j - 1]["end"]),
                    start + ILLUSTRATION_MAX_S,
                )
                if end - start < ILLUSTRATION_MIN_S:
                    end = min(duration, start + ILLUSTRATION_MIN_S)
                moments.append(
                    {
                        "start": start,
                        "end": end,
                        "text": " ".join(
                            w["text"].strip(".,!?;:")
                            for w in words[i:j]
                        ),
                        "prompt": " ".join(content).lower(),
                    }
                )
                last_start = trigger_start
                i = j
            else:
                i += 1

        return moments
