"""Provedor padrão: Claude (Anthropic Messages API).

Observação: a Claude não faz transcrição nem processa vídeo — ela recebe o
texto já transcrito (pelo Whisper) e toma as decisões criativas.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Union

from ai.base_provider import AIProvider
from ai.models import Callout, Highlight, MusicMood, TranscriptAnalysis

logger = logging.getLogger(__name__)


class ClaudeProvider(AIProvider):
    id = "claude"
    label = "Claude (Anthropic)"
    default_model = "claude-sonnet-4-5"
    env_key = "ANTHROPIC_API_KEY"

    _SYSTEM = (
        "Você é um diretor de edição de vídeos virais (Reels/TikTok/Shorts). "
        "Responda exclusivamente com JSON válido, sem markdown e sem texto extra."
    )

    def _client(self):
        if not self.api_key:
            raise ValueError(
                "API key do Claude não configurada. "
                "Defina-a em Configurações > Provedores de IA."
            )
        import anthropic  # import lazy: só é necessário quando a IA é usada

        return anthropic.Anthropic(api_key=self.api_key)

    def _json(self, prompt: str) -> Union[dict, list]:
        client = self._client()
        response = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self._SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> Union[dict, list]:
        text = text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            if len(parts) >= 2:
                text = parts[1].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
            end = max(text.rfind("}"), text.rfind("]"))
            if starts and end > min(starts):
                return json.loads(text[min(starts) : end + 1])
            raise

    # ------------------------------------------------------------------
    # Contrato AIProvider
    # ------------------------------------------------------------------

    def analyze_transcript(
        self, transcript_text: str, language: str = "pt"
    ) -> TranscriptAnalysis:
        prompt = (
            f"Analise a transcrição de vídeo a seguir (idioma: {language}). "
            "Retorne JSON com as chaves: summary (string), tone (string), "
            f"keywords (lista de strings).\n\nTranscrição:\n{transcript_text}"
        )
        data = self._json(prompt)
        if not isinstance(data, dict):
            raise ValueError("Resposta inesperada do Claude (esperado objeto).")
        return TranscriptAnalysis(
            summary=str(data.get("summary", "")),
            tone=str(data.get("tone", "")),
            keywords=[str(k) for k in data.get("keywords", [])],
        )

    def suggest_highlights(
        self,
        transcript_text: str,
        segments: Optional[list[dict]] = None,
        max_highlights: int = 5,
    ) -> list[Highlight]:
        seg_text = ""
        if segments:
            lines = [
                f"[{float(s.get('start', 0)):.1f}-{float(s.get('end', 0)):.1f}s] "
                f"{s.get('text', '')}"
                for s in segments
            ]
            seg_text = "Trechos com tempo:\n" + "\n".join(lines)
        prompt = (
            "Identifique os melhores momentos desta transcrição para destaque "
            f"em um vídeo viral (máximo {max_highlights}). "
            "Retorne um array JSON de objetos com as chaves: text, start "
            "(segundos), end (segundos), reason, score (0 a 1).\n"
            f"{seg_text}\n\nTranscrição:\n{transcript_text}"
        )
        data = self._json(prompt)
        if not isinstance(data, list):
            raise ValueError("Resposta inesperada do Claude (esperado array).")
        return [
            Highlight(
                text=str(item.get("text", "")),
                start=float(item.get("start", 0)),
                end=float(item.get("end", 0)),
                reason=str(item.get("reason", "")),
                score=float(item.get("score", 0)),
            )
            for item in data[:max_highlights]
            if isinstance(item, dict)
        ]

    def generate_caption_text(
        self, transcript_text: str, max_callouts: int = 5
    ) -> list[Callout]:
        prompt = (
            "A partir da transcrição, gere call-outs de vídeo viral: frases "
            "curtas e impactantes para aparecer em texto grande na tela. "
            f"Retorne no máximo {max_callouts}. Formato: array JSON de objetos "
            "com as chaves: text, emphasis ('alta', 'média' ou 'baixa').\n\n"
            f"Transcrição:\n{transcript_text}"
        )
        data = self._json(prompt)
        if not isinstance(data, list):
            raise ValueError("Resposta inesperada do Claude (esperado array).")
        return [
            Callout(text=str(item.get("text", "")), emphasis=str(item.get("emphasis", "alta")))
            for item in data[:max_callouts]
            if isinstance(item, dict)
        ]

    def suggest_music_mood(self, transcript_text: str) -> MusicMood:
        prompt = (
            "Sugira o clima ideal da música de fundo para esta transcrição. "
            "Retorne JSON com as chaves: mood (string), energy (0 a 1), "
            "keywords (lista de strings), suggested_bpm (inteiro).\n\n"
            f"Transcrição:\n{transcript_text}"
        )
        data = self._json(prompt)
        if not isinstance(data, dict):
            raise ValueError("Resposta inesperada do Claude (esperado objeto).")
        return MusicMood(
            mood=str(data.get("mood", "energético")),
            energy=float(data.get("energy", 0.7)),
            keywords=[str(k) for k in data.get("keywords", [])],
            suggested_bpm=int(data.get("suggested_bpm", 120)),
        )

    def suggest_edit_plan(
        self,
        transcript_text: str,
        segments: list[dict],
        duration: float,
        language: str = "pt",
    ) -> dict:
        seg_lines = [
            f"[{float(s.get('start', 0)):.2f}-{float(s.get('end', 0)):.2f}] "
            f"{s.get('text', '')}"
            for s in segments
        ]
        prompt = (
            "Você é editor de vídeos virais. Analise a transcrição palavra a "
            "palavra (timestamps em segundos) e monte um plano de edição.\n\n"
            "Regras:\n"
            "1. cuts: intervalos para REMOVER — silêncios, pausas longas, "
            "repetições e trechos sem valor. Use os timestamps exatos dos "
            f"gaps (duração do vídeo: {duration:.1f}s). No máximo 12 cortes.\n"
            "2. zooms: momentos de ÊNFASE para zoom punch-in (start/end em "
            "segundos, intensity entre 0.1 e 0.25). No máximo 4.\n"
            "3. transition_type: um de [corte, fade, slideleft, slideup, "
            "circleopen, dissolve, pixelize, wipeleft] nos pontos de corte.\n"
            "4. transition_duration: entre 0.2 e 0.5.\n\n"
            "Retorne EXATAMENTE este JSON (sem texto extra):\n"
            '{"cuts": [{"start": 0.0, "end": 0.0, "reason": "..."}], '
            '"zooms": [{"start": 0.0, "end": 0.0, "intensity": 0.15, '
            '"reason": "..."}], "transition_type": "fade", '
            '"transition_duration": 0.3}\n\n'
            "Palavras (start-end texto):\n" + "\n".join(seg_lines) + "\n\n"
            f"Texto completo:\n{transcript_text}"
        )
        data = self._json(prompt)
        if not isinstance(data, dict):
            raise ValueError("Resposta inesperada do Claude (esperado objeto).")
        return {
            "cuts": data.get("cuts", []),
            "zooms": data.get("zooms", []),
            "transition_type": str(data.get("transition_type", "fade")),
            "transition_duration": float(
                data.get("transition_duration", 0.3)
            ),
        }
