"""Provedor OpenAI/GPT — implementação do contrato AIProvider.

Usa a Chat Completions API. Compatível com a OpenAI oficial e com
provedores compatíveis (ex.: Groq, DeepSeek, xAI) via URL base customizada.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Union

from ai.base_provider import AIProvider
from ai.models import Callout, Highlight, MusicMood, TranscriptAnalysis

logger = logging.getLogger(__name__)


_SYSTEM = (
    "Você é um diretor de edição de vídeos virais (Reels/TikTok/Shorts). "
    "Responda exclusivamente com JSON válido, sem markdown e sem texto extra."
)


class OpenAIProvider(AIProvider):
    id = "openai"
    label = "OpenAI / GPT"
    default_model = "gpt-4o-mini"
    env_key = "OPENAI_API_KEY"
    supports_base_url = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model)
        self.base_url = base_url

    def _client(self):
        if not self.api_key:
            raise ValueError(
                "API key da OpenAI não configurada. "
                "Defina-a em Configurações > Provedores de IA."
            )
        import openai  # import lazy

        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return openai.OpenAI(**kwargs)

    def _json(self, prompt: str) -> Union[dict, list]:
        client = self._client()
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.4,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
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
            raise ValueError("Resposta inesperada (esperado objeto).")
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
            raise ValueError("Resposta inesperada (esperado array).")
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
            raise ValueError("Resposta inesperada (esperado array).")
        return [
            Callout(
                text=str(item.get("text", "")),
                emphasis=str(item.get("emphasis", "alta")),
            )
            for item in data[:max_callouts]
            if isinstance(item, dict)
        ]

    def suggest_music_mood(
        self, transcript_text: str, segments=None
    ) -> MusicMood:
        rate_hint = ""
        if segments:
            words = [s for s in segments if s.get("text", "").strip()]
            if words:
                dur = max(
                    0.1, float(words[-1]["end"]) - float(words[0]["start"])
                )
                rate_hint = (
                    f"\nRitmo da fala: {len(words) / dur:.1f} palavras/segundo."
                )
        prompt = (
            "Sugira o clima ideal da música de fundo para esta transcrição. "
            "Retorne JSON com as chaves: mood (string), energy (0 a 1), "
            "keywords (lista de strings), suggested_bpm (inteiro)."
            f"{rate_hint}\n\nTranscrição:\n{transcript_text}"
        )
        data = self._json(prompt)
        if not isinstance(data, dict):
            raise ValueError("Resposta inesperada (esperado objeto).")
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
            "glitch]. Para talking head viral, prefira 'corte'.\n"
            "4. transition_duration: entre 0.05 e 0.5 (segundos).\n\n"
            "Retorne EXATAMENTE este JSON (sem texto extra):\n"
            '{"cuts": [{"start": 0.0, "end": 0.0, "reason": "silêncio"}], '
            '"zooms": [{"start": 0.0, "end": 0.0, "intensity": 0.15, '
            '"reason": "ênfase"}], "transition_type": "corte", '
            '"transition_duration": 0.1}\n\n'
            "Trechos:\n"
            + "\n".join(seg_lines)
            + "\n\nTranscrição:\n"
            + transcript_text
        )
        data = self._json(prompt)
        if not isinstance(data, dict):
            raise ValueError("Resposta inesperada (esperado objeto).")
        return {
            "cuts": [
                {
                    "start": float(c.get("start", 0)),
                    "end": float(c.get("end", 0)),
                    "reason": str(c.get("reason", "")),
                }
                for c in data.get("cuts", [])
                if isinstance(c, dict)
            ],
            "zooms": [
                {
                    "start": float(z.get("start", 0)),
                    "end": float(z.get("end", 0)),
                    "intensity": float(z.get("intensity", 0.15)),
                    "reason": str(z.get("reason", "")),
                }
                for z in data.get("zooms", [])
                if isinstance(z, dict)
            ],
            "transition_type": str(
                data.get("transition_type", "corte")
            ),
            "transition_duration": float(
                data.get("transition_duration", 0.1)
            ),
        }

    def suggest_illustration_moments(
        self,
        transcript_text: str,
        segments: list[dict],
        duration: float,
        language: str = "pt",
        density_s: float = 8.0,
    ) -> list[dict]:
        seg_lines = [
            f"[{float(s.get('start', 0)):.2f}-{float(s.get('end', 0)):.2f}] "
            f"{s.get('text', '')}"
            for s in segments
        ]
        prompt = (
            "Você é editor de vídeos virais. Analise a transcrição palavra a "
            "palavra e sugira momentos para DESTAQUES visuais (call-outs de "
            "texto ou imagens) que acompanhem a fala.\n\n"
            "Regras:\n"
            "1. Só sugira quando a fala mencionar algo visualmente concreto: "
            "lugares, objetos, conceitos, exemplos.\n"
            "2. Cada sugestão deve incluir kind='callout' por padrão e "
            "callout_text com uma palavra ou frase curta, grande e "
            "impactante. O usuário poderá trocar para imagem na revisão.\n"
            "3. No máximo 1 sugestão a cada "
            f"{density_s:.0f}s de fala (vídeo: {duration:.1f}s).\n"
            "4. start/end = começo/fim da fala que o destaque deve acompanhar "
            "(timestamps exatos das palavras).\n"
            "5. prompt = descrição curta da imagem, no idioma da fala, "
            "otimizada para busca em banco de imagens ou geração por IA "
            f"({language}). Sem nomes próprios de pessoas.\n\n"
            "Retorne EXATAMENTE este JSON (sem texto extra):\n"
            '{"moments": [{"start": 0.0, "end": 0.0, "text": "trecho dito", '
            '"prompt": "descrição da imagem", "kind": "callout", '
            '"callout_text": "FRASE CURTA"}]}\n\n'
            "Trechos:\n"
            + "\n".join(seg_lines)
            + "\n\nTranscrição:\n"
            + transcript_text
        )
        data = self._json(prompt)
        if not isinstance(data, dict):
            raise ValueError("Resposta inesperada (esperado objeto).")
        moments = data.get("moments", [])
        if not isinstance(moments, list):
            raise ValueError("Resposta inesperada (esperado array).")
        return [
            {
                "start": float(item.get("start", 0)),
                "end": float(item.get("end", 0)),
                "text": str(item.get("text", "")),
                "prompt": str(item.get("prompt", "")),
                "kind": str(item.get("kind", "callout")),
                "callout_text": str(
                    item.get("callout_text", "")
                    or item.get("text", "")
                    or item.get("prompt", "")
                ),
            }
            for item in moments
            if isinstance(item, dict)
        ]
