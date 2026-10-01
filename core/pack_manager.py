"""Pack externo de assets (Fase 7): fontes, LUTs, setas, memes, overlays…

Indexa um pack estilo CapCut em HD externo (ex.: E:\\Packs CapCut\\...) SEM
embutir nada no instalador: tudo é lido em tempo de execução. Se o HD
estiver desconectado, as categorias ficam vazias e o app segue com os
assets padrão — nunca trava.

Cada categoria tem sua própria pasta configurável (Settings.pack_folders);
opcionalmente uma pasta raiz (Settings.pack_root) é auto-detectada pelos
nomes de subpastas (ex.: "4 - Transições").
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_FILES_PER_CATEGORY = 2000
MAX_SCAN_DEPTH = 3

# ---------------------------------------------------------------------------
# Categorias do pack (id, rótulo, palavras-chave de pasta, extensões)
# ---------------------------------------------------------------------------

CAT_VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
CAT_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}
CAT_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
CAT_FONT_EXT = {".ttf", ".otf"}
CAT_LUT_EXT = {".cube", ".3dl"}

PACK_CATEGORIES: dict[str, dict] = {
    "efeitos_anuncios": {
        "label": "Efeitos de anúncios",
        "keywords": ("efeitos", "anuncio", "anuncios", "ads"),
        "exts": CAT_VIDEO_EXT | CAT_IMAGE_EXT,
    },
    "backgrounds": {
        "label": "Backgrounds",
        "keywords": ("background", "backgrounds", "fundo"),
        "exts": CAT_VIDEO_EXT | CAT_IMAGE_EXT,
    },
    "overlays": {
        "label": "Overlays",
        "keywords": ("overlay", "overlays"),
        "exts": CAT_VIDEO_EXT | CAT_IMAGE_EXT,
    },
    "transicoes": {
        "label": "Transições",
        "keywords": ("transicao", "transicoes", "transition"),
        "exts": CAT_VIDEO_EXT,
    },
    "light_leaks": {
        "label": "Light leaks",
        "keywords": ("light", "leak", "leaks", "bokeh"),
        "exts": CAT_VIDEO_EXT,
    },
    "sfx": {
        "label": "Efeitos sonoros",
        "keywords": ("sound", "sfx", "efeitos sonoros"),
        "exts": CAT_AUDIO_EXT,
    },
    "musica": {
        "label": "Música de fundo",
        "keywords": ("musica", "music", "trilha"),
        "exts": CAT_AUDIO_EXT,
    },
    "elementos": {
        "label": "Elementos",
        "keywords": ("elemento", "elementos", "elements"),
        "exts": CAT_VIDEO_EXT | CAT_IMAGE_EXT,
    },
    "personagens": {
        "label": "Personagens virais",
        "keywords": ("personagem", "personagens", "character"),
        "exts": CAT_VIDEO_EXT | CAT_IMAGE_EXT,
    },
    "emojis": {
        "label": "Emojis",
        "keywords": ("emoji", "emojis"),
        "exts": CAT_IMAGE_EXT | CAT_VIDEO_EXT,
    },
    "icones": {
        "label": "Ícones",
        "keywords": ("icone", "icones", "icon", "icons"),
        "exts": CAT_IMAGE_EXT,
    },
    "gifs": {
        "label": "GIFs",
        "keywords": ("gif", "gifs", "sticker", "stickers"),
        "exts": {".gif"} | CAT_VIDEO_EXT,
    },
    "fontes": {
        "label": "Fontes",
        "keywords": ("fonte", "fontes", "font", "fonts"),
        "exts": CAT_FONT_EXT,
    },
    "luts": {
        "label": "LUTs",
        "keywords": ("lut", "luts", "color", "cor"),
        "exts": CAT_LUT_EXT,
    },
    "memes": {
        "label": "Memes",
        "keywords": ("meme", "memes"),
        "exts": CAT_IMAGE_EXT | CAT_VIDEO_EXT,
    },
    "setas": {
        "label": "Setas",
        "keywords": ("seta", "setas", "arrow", "arrows"),
        "exts": CAT_IMAGE_EXT | CAT_VIDEO_EXT,
    },
    "stock": {
        "label": "Stock videos",
        "keywords": ("stock", "video", "videos"),
        "exts": CAT_VIDEO_EXT,
    },
}

# Categorias aplicadas automaticamente pela IA no render (sempre revisáveis).
AUTO_APPLY_CATEGORIES = {"overlays", "light_leaks", "emojis", "gifs", "sfx", "luts"}

# Categorias indexadas para uso manual futuro (sem interface ainda).
MANUAL_ONLY_CATEGORIES = {
    "efeitos_anuncios", "backgrounds", "transicoes", "musica",
    "elementos", "personagens", "icones", "memes", "setas", "stock",
}


def _norm(text: str) -> str:
    """minúsculas + sem acentos, para casar nomes de pasta."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


@dataclass
class PackItem:
    """Um arquivo do pack externo."""

    path: Path
    category: str
    name: str  # nome amigável (stem)

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "category": self.category,
            "name": self.name,
        }


@dataclass
class PackSuggestion:
    """Sugestão da IA/heurística de uso de um item do pack.

    kind: overlay | sfx | lut — sempre revisável na tela de revisão;
    nada é aplicado sem aprovação.
    """

    kind: str
    path: Path
    category: str
    start: float = 0.0
    end: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "category": self.category,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PackSuggestion":
        return cls(
            kind=str(data.get("kind", "overlay")),
            path=Path(data.get("path", "")),
            category=str(data.get("category", "")),
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            reason=str(data.get("reason", "")),
        )


def suggestions_to_json(items: list[PackSuggestion], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([i.to_dict() for i in items], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def suggestions_from_json(path: Path) -> list[PackSuggestion]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [PackSuggestion.from_dict(d) for d in raw if isinstance(d, dict)]


class PackManager:
    """Indexa e consulta o pack externo de assets."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self._index: dict[str, list[PackItem]] = {}
        self._missing: list[str] = []
        self.scanned = False

    # ------------------------------------------------------------------
    # Configuração de pastas
    # ------------------------------------------------------------------

    def configured_folder(self, category: str) -> Optional[Path]:
        """Pasta da categoria: override manual > auto-detect na raiz > None."""
        folders = getattr(self.settings, "pack_folders", {}) or {}
        raw = folders.get(category, "")
        if raw and Path(raw).is_dir():
            return Path(raw)
        # auto-detect na pasta raiz pelos keywords da categoria
        root = getattr(self.settings, "pack_root", "") or ""
        if root and Path(root).is_dir():
            keywords = PACK_CATEGORIES[category]["keywords"]
            for entry in sorted(Path(root).iterdir()):
                if not entry.is_dir():
                    continue
                name = _norm(entry.name)
                if any(k in name for k in keywords):
                    return entry
        return None

    def detect_categories_from_root(self) -> int:
        """Preenche pack_folders com as pastas auto-detectadas na raiz."""
        root = getattr(self.settings, "pack_root", "") or ""
        if not root or not Path(root).is_dir():
            return 0
        folders = dict(getattr(self.settings, "pack_folders", {}) or {})
        detected = 0
        for category, meta in PACK_CATEGORIES.items():
            path = self.configured_folder(category)
            if path is not None and str(path) != folders.get(category, ""):
                folders[category] = str(path)
                detected += 1
        self.settings.pack_folders = folders
        return detected

    def missing_categories(self) -> list[str]:
        """Rótulos das categorias configuradas cuja pasta não existe agora
        (HD desconectado)."""
        folders = getattr(self.settings, "pack_folders", {}) or {}
        missing = []
        for category, raw in folders.items():
            if raw and not Path(raw).is_dir():
                missing.append(PACK_CATEGORIES.get(category, {}).get("label", category))
        return missing

    # ------------------------------------------------------------------
    # Scan / índice
    # ------------------------------------------------------------------

    def scan(self) -> dict[str, list[PackItem]]:
        """Varre as pastas configuradas e monta o índice por categoria.

        Lento apenas na primeira vez; nunca lança exceção — pasta
        inacessível só gera aviso (HD desconectado).
        """
        self._index = {}
        self._missing = []
        for category, meta in PACK_CATEGORIES.items():
            folder = self.configured_folder(category)
            items: list[PackItem] = []
            if folder is None:
                folders_cfg = getattr(self.settings, "pack_folders", {}) or {}
                if folders_cfg.get(category):
                    self._missing.append(meta["label"])
            else:
                try:
                    items = self._scan_folder(folder, category, meta["exts"])
                except OSError as exc:
                    logger.warning(
                        "Pack '%s' inacessível (%s); seguindo sem ele.",
                        meta["label"], exc,
                    )
                    self._missing.append(meta["label"])
            self._index[category] = items
        self.scanned = True
        total = sum(len(v) for v in self._index.values())
        logger.info(
            "Pack indexado: %d arquivo(s) em %d categoria(s)%s",
            total, len(self._index),
            f" (ausentes: {', '.join(self._missing)})" if self._missing else "",
        )
        return self._index

    def rescan(self) -> dict[str, list[PackItem]]:
        return self.scan()

    @staticmethod
    def _scan_folder(folder: Path, category: str, exts: set[str]) -> list[PackItem]:
        items: list[PackItem] = []
        base_depth = len(folder.parts)
        stack = [(folder, 0)]
        while stack and len(items) < MAX_FILES_PER_CATEGORY:
            current, depth = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError as exc:
                logger.warning("Pasta ilegível %s: %s", current, exc)
                continue
            for entry in entries:
                if entry.is_dir():
                    if depth + 1 < MAX_SCAN_DEPTH:
                        stack.append((entry, depth + 1))
                    continue
                if entry.suffix.lower() in exts:
                    items.append(
                        PackItem(path=entry, category=category, name=entry.stem)
                    )
                    if len(items) >= MAX_FILES_PER_CATEGORY:
                        logger.warning(
                            "Categoria '%s' excedeu %d arquivos; indexação truncada.",
                            category, MAX_FILES_PER_CATEGORY,
                        )
                        break
        # profundidade relativa não usada além do limite; parts check implícito
        del base_depth
        return items

    def items(self, category: str) -> list[PackItem]:
        if not self.scanned:
            self.scan()
        return self._index.get(category, [])

    def all_items(self) -> list[PackItem]:
        if not self.scanned:
            self.scan()
        return [i for items in self._index.values() for i in items]

    def category_items(self, category: str) -> list[PackItem]:
        return list(self.items(category))

    def fonts(self) -> list[PackItem]:
        return list(self.items("fontes"))

    def luts(self) -> list[PackItem]:
        return list(self.items("luts"))

    def music_folders(self) -> list[Path]:
        """Pastas de música do pack (para o MusicManager)."""
        folder = self.configured_folder("musica")
        return [folder] if folder else []

    # ------------------------------------------------------------------
    # Sugestão automática (heurística; a IA revisável entra na tela de revisão)
    # ------------------------------------------------------------------

    def suggest_usages(
        self,
        words: list[dict],
        duration: float,
        mood: str = "",
        max_overlays: int = 6,
        max_sfx: int = 6,
    ) -> list[PackSuggestion]:
        """Sugere overlays/elementos e SFX do pack casando nomes com a fala.

        - overlay: nome do asset (>= 4 letras) citado na transcrição →
          aparece por ~2.5s cobrindo a menção.
        - sfx: assets de áudio com nome casando palavra enfática.
        - lut: um LUT do pack sugerido pelo clima (1 no máximo).
        Conservadora: sem casamento, não sugere nada.
        """
        suggestions: list[PackSuggestion] = []
        overlay_cats = ("overlays", "light_leaks", "emojis", "gifs", "elementos")

        tokens = [
            (w["text"].strip(".,!?;:").lower(), float(w["start"]), float(w["end"]))
            for w in words
            if w.get("text", "").strip()
        ]

        last_end = -1e9
        for category in overlay_cats:
            for item in self.items(category):
                if len(suggestions) >= max_overlays:
                    break
                key = _norm(item.name)
                if len(key) < 4:
                    continue
                # casamento: qualquer palavra do nome do asset (>= 4 letras)
                # citada na fala (ex.: "money rain" casa com "money")
                key_tokens = [t for t in key.split() if len(t) >= 4]
                if not key_tokens:
                    continue
                matched = next(
                    (
                        (s, e)
                        for text, s, e in tokens
                        if any(
                            kt == text
                            or (len(kt) >= 5 and kt in text)
                            or (len(text) >= 4 and text in kt)
                            for kt in key_tokens
                        )
                    ),
                    None,
                )
                if matched is None:
                    continue
                start, end = matched
                if start - last_end < 2.0:
                    continue
                s = max(0.0, start - 0.2)
                e = min(duration, end + 2.0)
                if e - s < 1.0:
                    continue
                suggestions.append(
                    PackSuggestion(
                        kind="overlay",
                        path=item.path,
                        category=category,
                        start=s,
                        end=e,
                        reason=f"“{item.name}” citado na fala",
                    )
                )
                last_end = e

        for item in self.items("sfx"):
            if len(suggestions) >= max_overlays + max_sfx:
                break
            key = _norm(item.name)
            if len(key) < 4:
                continue
            key_tokens = [t for t in key.split() if len(t) >= 4]
            if not key_tokens:
                continue
            matched = next(
                (
                    (t, s, e)
                    for t, s, e in tokens
                    if any(kt == t or (len(kt) >= 5 and kt in t) for kt in key_tokens)
                ),
                None,
            )
            if matched is None:
                continue
            _, start, _ = matched
            if any(abs(g.start - start) < 2.0 for g in suggestions if g.kind == "sfx"):
                continue
            suggestions.append(
                PackSuggestion(
                    kind="sfx",
                    path=item.path,
                    category="sfx",
                    start=max(0.0, start - 0.1),
                    end=max(0.0, start - 0.1),
                    reason=f"efeito “{item.name}” combina com a fala",
                )
            )

        # LUT pelo clima (máx. 1): nomes quentes p/ energia, frios p/ calma
        luts = self.luts()
        if luts:
            warm = ("warm", "quente", "sunset", "orange", "golden", "vibrant")
            cool = ("cool", "frio", "blue", "cyan", "cold", "cinematic")
            mood_l = _norm(mood)
            prefer = warm if any(k in mood_l for k in ("energ", "motiva")) else cool
            chosen = next(
                (l for l in luts if any(k in _norm(l.name) for k in prefer)),
                None,
            ) or luts[0]
            suggestions.append(
                PackSuggestion(
                    kind="lut",
                    path=chosen.path,
                    category="luts",
                    start=0.0,
                    end=duration,
                    reason=f"LUT “{chosen.name}” combina com o clima “{mood}”",
                )
            )

        return suggestions
