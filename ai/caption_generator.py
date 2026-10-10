"""Geração de legenda e hashtags para publicação nas redes sociais.

Tenta usar o provedor de IA ativo; se não houver chave ou der erro,
cai em uma heurística local que extrai palavras-chave do texto e
monta hashtags relevantes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Hashtags genéricas por nicho detectado no texto
_NICHE_HASHTAGS: dict[str, list[str]] = {
    "tecnologia": ["#tecnologia", "#inovação", "#tech", "#futuro"],
    "marketing": ["#marketingdigital", "#conteúdo", "#estrategia", "#crescimento"],
    "negocios": ["#empreendedorismo", "#negocios", "#sucesso", "#mindset"],
    "saude": ["#saúde", "#bemestar", "#fitness", "#vidasaudável"],
    "moda": ["#moda", "#estilo", "#look", "#tendencia"],
    "comida": ["#comida", "#receita", "#food", "#gastronomia"],
    "educacao": ["#educação", "#aprendizado", "#conhecimento", "#estudo"],
    "motivacao": ["#motivação", "#disciplina", "#foco", "#superação"],
}

# Palavras que não viram hashtag (stopwords + verbos comuns que raramente são hashtags)
_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "com", "sem", "sob", "sobre", "entre",
    "ate", "apos", "antes", "durante", "que", "se", "como", "mas", "ou", "e", "eh", "sao",
    "este", "esta", "isto", "esse", "essa", "isso", "aquele", "aquela", "aquilo", "meu",
    "minha", "seu", "sua", "dele", "dela", "mesmo", "muito", "mais", "menos", "tambem",
    "ja", "ainda", "agora", "depois", "hoje", "aqui", "ai", "la", "the", "and", "for",
    "with", "you", "this", "that", "from", "are", "was", "were", "have", "has", "had",
    "mudou", "mudar", "precisamos", "precisar", "fazer", "fazemos", "vamos", "vai", "ir",
    "nossas", "nossos", "suas", "minhas", "vidas", "vida", "temos", "ter", "essa", "esse",
    "essa", "novo", "nova", "novos", "novas", "cada", "todo", "toda", "todos", "todas",
    "assim", "pois", "porque", "quando", "onde", "qual", "quem", "cujo", "cuja",
}

# Sufixos que indicam substantivo/adjetivo em português/inglês
_GOOD_SUFFIXES = (
    "cao", "sao", "mento", "vel", "osa", "oso", "ismo", "ista", "idade", "ente",
    "ante", "avel", "ivel", "ico", "ica", "logia", "grafia", "nauta", "crata",
    "ing", "tion", "sion", "ment", "ness", "ity", "able", "ible", "ful", "less",
    "ive", "ous", "ic", "al", "ar", "er", "or",
)


@dataclass
class GeneratedCaption:
    """Resultado da geração de legenda."""

    caption: str
    hashtags: list[str]


def _detect_niche(text: str) -> str:
    """Identifica o nicho principal do conteúdo para sugerir hashtags base."""
    low = text.lower()
    scores: dict[str, int] = {}
    for niche, cues in {
        "tecnologia": ["tecnologia", "tech", "ia", "inteligencia artificial", "app", "software", "digital"],
        "marketing": ["marketing", "vendas", "cliente", "alcance", "engajamento", "conteúdo"],
        "negocios": ["negocio", "empresa", "empreender", "lucro", "faturamento", "empreendedor"],
        "saude": ["saude", "bem estar", "exercicio", "dieta", "corpo", "mente"],
        "moda": ["moda", "roupa", "estilo", "look", "tendencia"],
        "comida": ["comida", "receita", "cozinha", "restaurante", "sabor"],
        "educacao": ["educacao", "aprender", "estudar", "aula", "curso", "ensino"],
        "motivacao": ["motivacao", "foco", "disciplina", "sonho", "metas", "superar"],
    }.items():
        scores[niche] = sum(low.count(cue) for cue in cues)
    return max(scores, key=scores.get) if scores and max(scores.values()) > 0 else "motivacao"


def _heuristic_caption(text: str, platform: str = "reels") -> GeneratedCaption:
    """Gera legenda + hashtags localmente sem chamar API externa."""
    # Frases curtas e limpas
    sentences = [s.strip() for s in re.split(r"[.!?]", text) if s.strip()]
    summary = sentences[0] if sentences else text
    if len(summary) > 120:
        summary = summary[:117] + "..."

    # Extrai palavras frequentes e relevantes para hashtags
    words = re.findall(r"\b[a-zA-Zà-úÀ-Ú]{4,}\b", text.lower())

    def _good_word(w: str) -> bool:
        if w in _STOPWORDS:
            return False
        # Só aceita palavras com sufixo de substantivo/adjetivo ou com 6+ letras
        if any(w.endswith(suf) for suf in _GOOD_SUFFIXES):
            return True
        return len(w) >= 6

    freq: dict[str, int] = {}
    for w in words:
        if not _good_word(w):
            continue
        freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]
    tags = [f"#{w}" for w, _ in top]

    # Adiciona hashtags de nicho
    niche = _detect_niche(text)
    for t in _NICHE_HASHTAGS.get(niche, _NICHE_HASHTAGS["motivacao"]):
        if t not in tags:
            tags.append(t)

    # Hashtags de plataforma
    platform_tags = ["#reels", "#viral", "#shorts"] if platform in {"reels", "story"} else ["#feed", "#post"]
    for t in platform_tags:
        if t not in tags:
            tags.append(t)

    return GeneratedCaption(caption=summary, hashtags=tags[:10])


def generate_caption(
    text: str,
    provider_manager=None,
    platform: str = "reels",
    language: str = "pt",
) -> GeneratedCaption:
    """Gera legenda + hashtags. Tenta enriquecer com IA; se falhar, usa heurística local."""
    if not text or not text.strip():
        return GeneratedCaption(
            caption="",
            hashtags=["#reels", "#viral", "#shorts", "#conteúdo"],
        )

    provider = None
    if provider_manager is not None:
        try:
            provider = provider_manager.get_active()
        except Exception as exc:
            logger.debug("Provedor ativo indisponível para legenda: %s", exc)

    # Tenta enriquecer com palavras-chave/tema da IA
    ai_keywords: list[str] = []
    if provider is not None:
        try:
            analysis = provider.analyze_transcript(text[:1500], language=language)
            ai_keywords = [kw.strip().lower().replace(" ", "") for kw in (getattr(analysis, "keywords", []) or []) if kw.strip()]
        except Exception as exc:
            logger.debug("IA não conseguiu analisar para legenda: %s", exc)

    result = _heuristic_caption(text, platform)

    # Insere palavras-chave da IA como hashtags prioritárias
    if ai_keywords:
        ai_tags = [f"#{kw}" for kw in ai_keywords[:4] if kw not in _STOPWORDS]
        merged = ai_tags + [t for t in result.hashtags if t not in ai_tags]
        result.hashtags = merged[:10]

    return result
