"""Sugestão de uso do pack externo pelos provedores de IA (Fase 7).

O índice do pack é enviado de forma compacta (categoria + nome, sem
caminhos longos) e a resposta da IA é validada contra os caminhos reais
do índice — nada que não exista no pack é aceito.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_INDEX_ITEMS = 400  # mantém o prompt pequeno
MAX_SUGGESTIONS = 12
VALID_KINDS = {"overlay", "sfx", "lut"}
OVERLAY_DURATION_S = 2.5

PROMPT_TEMPLATE = (
    "Transcrição do vídeo (com timestamps por palavra):\n"
    "{transcript}\n\n"
    "Biblioteca de assets disponíveis (categoria | nome):\n"
    "{index}\n\n"
    "Escolha no máximo {max_items} assets que combinam com o conteúdo falado, "
    "para deixar a edição mais profissional. Regras:\n"
    "- kind: 'overlay' para vídeos/imagens visuais, 'sfx' para áudio, "
    "'lut' para correção de cor (no máximo 1 lut).\n"
    "- Só sugira assets cujo nome/faixa faça sentido no contexto da fala.\n"
    "- Para overlay/sfx, 'start'/'end' são segundos no vídeo (end-start ~2-3s "
    "para overlay; start==end para sfx). Para lut, start=0 e end=duração "
    "({duration:.1f}s).\n"
    "- Se nada combinar bem, responda [].\n"
    "Responda exclusivamente com JSON: lista de "
    '[{{"kind": "...", "category": "...", "name": "...", "start": 0.0, '
    '"end": 0.0, "reason": "motivo curto"}}]'
)


def build_pack_index(items) -> list[dict]:
    """PackItem(s) → índice compacto para o prompt."""
    index = []
    for item in items:
        index.append(
            {"category": item.category, "name": item.name, "path": str(item.path)}
        )
    return index[:MAX_INDEX_ITEMS]


def build_prompt(
    transcript_text: str,
    pack_index: list[dict],
    duration: float,
    max_items: int = MAX_SUGGESTIONS,
) -> str:
    lines = [f"{i['category']} | {i['name']}" for i in pack_index]
    transcript = transcript_text[:6000]
    return PROMPT_TEMPLATE.format(
        transcript=transcript,
        index="\n".join(lines) or "(vazia)",
        max_items=max_items,
        duration=duration,
    )


def validate_suggestions(
    raw,
    pack_index: list[dict],
    duration: float,
) -> list[dict]:
    """Filtra a resposta da IA: só caminhos que existem no índice."""
    if not isinstance(raw, list):
        return []
    by_key: dict[tuple[str, str], dict] = {}
    for item in pack_index:
        by_key[(item["category"], item["name"].lower())] = item
        by_key[("*", Path(item["path"]).name.lower())] = item

    validated: list[dict] = []
    seen_paths: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict) or len(validated) >= MAX_SUGGESTIONS:
            continue
        kind = str(entry.get("kind", "")).lower()
        if kind not in VALID_KINDS:
            continue
        category = str(entry.get("category", "")).lower()
        name = str(entry.get("name", "")).lower()
        item = by_key.get((category, name)) or by_key.get(("*", name))
        if item is None:
            continue
        path = item["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)
        start = max(0.0, float(entry.get("start", 0.0) or 0.0))
        if kind == "lut":
            end = duration
            start = 0.0
        else:
            end = float(entry.get("end", start + OVERLAY_DURATION_S) or start)
        if kind == "overlay" and end - start < 0.5:
            end = start + OVERLAY_DURATION_S
        end = min(end, duration if kind == "lut" else max(duration, end))
        validated.append(
            {
                "kind": kind,
                "path": path,
                "category": item["category"],
                "start": start,
                "end": end,
                "reason": str(entry.get("reason", ""))[:120],
            }
        )
    return validated


class PackSuggestMixin:
    """Adiciona `suggest_pack_usage` a provedores que têm `_json(prompt)`.

    Se a IA falhar (rede/quota/modelo), retorna [] — a heurística local
    do core/pack_manager.py complementa as sugestões no pipeline.
    """

    def suggest_pack_usage(
        self,
        transcript_text: str,
        segments: list[dict],
        duration: float,
        pack_index: Optional[list[dict]] = None,
        language: str = "pt",
    ) -> list[dict]:
        index = list(pack_index or [])
        if not index:
            return []
        prompt = build_prompt(transcript_text, index, duration)
        try:
            raw = self._json(prompt)
        except Exception as exc:
            logger.warning("IA não sugeriu assets do pack: %s", exc)
            return []
        return validate_suggestions(raw, index, duration)
