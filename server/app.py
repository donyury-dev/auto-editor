"""Servidor local do Auto Editor Web.

Expõe a análise (transcrição + planos), a timeline editável, o streaming
do vídeo, o render final e a biblioteca do pack externo via HTTP + SSE.
Reaproveita integralmente o core Python do projeto (pipeline, EditPlan,
VideoProcessor, PackManager) — nenhuma lógica de edição é reescrita.
"""

from __future__ import annotations

import json
import logging
import queue
import secrets
import threading
import time
import uuid
import os
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import traceback

from audio.music_manager import MusicManager
from config.settings import DATA_DIR, OUTPUT_DIR, Settings
from core.edit_plan import TRANSITION_TYPES, Cut, EditPlan, ZoomEffect
from core.illustration_plan import IllustrationMoment
from images.manager import ImageProviderManager
from core.pipeline import (
    PipelineContext,
    build_analysis_pipeline,
    build_render_pipeline,
)
from core.pack_manager import PackManager
from ai.provider_manager import ProviderManager
from core.templates import TemplateManager, ensure_caption_preset
from core.transcriber import Transcript

logger = logging.getLogger(__name__)

PROJECTS_DIR = OUTPUT_DIR / "web_projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

app = FastAPI(title="Auto Editor Web")

_EDITOR_SESSIONS: dict[str, datetime] = {}
_KALBIX_SUPABASE_URL = os.getenv(
    "KALBIX_SUPABASE_URL",
    "https://nifqzxoyelqbpawovurn.supabase.co",
).rstrip("/")
_KALBIX_SUPABASE_ANON_KEY = os.getenv(
    "KALBIX_SUPABASE_ANON_KEY",
    "sb_publishable_G_tj35zEeJEeYDZ7e5LnQw_l0QP35HC",
)
_OPEN_API_PATHS = (
    "/api/access",
    "/api/health",
    "/api/debug/",
    "/api/public-video/",
    "/api/instagram/oauth/",
)


def _editor_access_allowed(access: dict[str, Any] | None) -> bool:
    if not access or access.get("manual_revoked"):
        return False
    if access.get("plan") == "full" or access.get("manual_grant"):
        return True
    included_until = access.get("included_until")
    if not included_until:
        return False
    try:
        return date.fromisoformat(str(included_until)[:10]) >= date.today()
    except ValueError:
        return False


def _supabase_get(path: str, access_token: str) -> Any:
    req = urllib.request.Request(
        f"{_KALBIX_SUPABASE_URL}{path}",
        headers={
            "apikey": _KALBIX_SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _validate_editor_token(access_token: str) -> bool:
    if not access_token:
        return False
    try:
        user = _supabase_get("/auth/v1/user", access_token)
        user_id = user.get("id")
        if not user_id:
            return False
        profiles = _supabase_get(
            f"/rest/v1/profiles?select=tenant_id&user_id=eq.{user_id}&limit=1",
            access_token,
        )
        tenant_id = profiles[0].get("tenant_id") if profiles else None
        if not tenant_id:
            return False
        accesses = _supabase_get(
            f"/rest/v1/editor_access?select=plan,included_until,manual_grant,manual_revoked"
            f"&tenant_id=eq.{tenant_id}&limit=1",
            access_token,
        )
        return _editor_access_allowed(accesses[0] if accesses else None)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("Falha ao validar acesso do editor: %s", exc)
        return False


def _validate_editor_token_debug(access_token: str) -> dict[str, Any]:
    """Retorna detalhes da validação para diagnóstico (sem expor a senha/token)."""
    result: dict[str, Any] = {"token_present": bool(access_token), "steps": []}
    if not access_token:
        result["allowed"] = False
        result["reason"] = "access_token vazio"
        return result
    try:
        user = _supabase_get("/auth/v1/user", access_token)
        user_id = user.get("id")
        result["steps"].append({"step": "auth_user", "user_id": user_id, "email": user.get("email")})
        if not user_id:
            result["allowed"] = False
            result["reason"] = "token não retornou user_id"
            return result

        profiles = _supabase_get(
            f"/rest/v1/profiles?select=tenant_id,role&user_id=eq.{user_id}&limit=1",
            access_token,
        )
        result["steps"].append({"step": "profiles", "profiles": profiles})
        tenant_id = profiles[0].get("tenant_id") if profiles else None
        if not tenant_id:
            result["allowed"] = False
            result["reason"] = "usuário sem tenant vinculado"
            return result

        accesses = _supabase_get(
            f"/rest/v1/editor_access?select=plan,included_until,manual_grant,manual_revoked"
            f"&tenant_id=eq.{tenant_id}&limit=1",
            access_token,
        )
        result["steps"].append({"step": "editor_access", "access": accesses})
        access = accesses[0] if accesses else None
        allowed = _editor_access_allowed(access)
        result["allowed"] = allowed
        result["reason"] = (
            "acesso liberado"
            if allowed
            else "editor_access não encontrado ou não liberado"
        )
        return result
    except Exception as exc:
        result["allowed"] = False
        result["reason"] = f"exceção: {type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        return result


@app.get("/api/debug/access")
def debug_editor_access(access_token: str = ""):
    """Endpoint de diagnóstico: por que o acesso foi negado?"""
    diag = _validate_editor_token_debug(access_token)
    return JSONResponse(diag)


@app.middleware("http")
async def require_editor_access(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or any(path.startswith(p) for p in _OPEN_API_PATHS):
        return await call_next(request)

    session = request.cookies.get("kalbix_editor_session", "")
    expires = _EDITOR_SESSIONS.get(session)
    if not session or not expires or expires <= datetime.now(timezone.utc):
        return JSONResponse({"error": "Acesso ao editor não autorizado."}, status_code=403)
    return await call_next(request)


@app.get("/api/access")
def editor_access(request: Request, access_token: str = ""):
    session = request.cookies.get("kalbix_editor_session", "")
    if session and _EDITOR_SESSIONS.get(session, datetime.min.replace(tzinfo=timezone.utc)) > datetime.now(timezone.utc):
        return {"allowed": True}
    if not _validate_editor_token(access_token):
        raise HTTPException(403, "Seu acesso ao editor não está liberado pelo administrador.")
    session = secrets.token_urlsafe(32)
    _EDITOR_SESSIONS[session] = datetime.now(timezone.utc) + timedelta(hours=12)
    response = JSONResponse({"allowed": True})
    response.set_cookie(
        "kalbix_editor_session",
        session,
        max_age=43200,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


# ----------------------------------------------------------------------
# Estado em memória
# ----------------------------------------------------------------------


@dataclass
class ProjectState:
    """Um projeto aberto no editor web."""

    id: str
    video_path: Path
    settings: Settings
    manager: ProviderManager
    image_manager: ImageProviderManager
    music_manager: MusicManager
    pack_manager: PackManager
    ctx: Optional[PipelineContext] = None
    status: str = "new"  # new | analyzing | ready | rendering | done | failed
    error: str = ""
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    # timeline editável (fonte de verdade pós-análise)
    timeline: dict = field(default_factory=dict)
    # legenda + hashtags geradas para publicação social
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    # token para URL pública temporária do vídeo renderizado (usado pelo Meta)
    public_token: str = ""

    def emit(self, kind: str, **data: Any) -> None:
        payload = {"kind": kind, **data}
        self.events.put(payload)

    def emit_progress(self, overall: float, step: str, msg: str) -> None:
        self.emit("progress", overall=round(overall, 4), step=step, msg=msg)


PROJECTS: dict[str, ProjectState] = {}

# Mapeia token público -> project_id para o endpoint /api/public-video/{token}
_PUBLIC_VIDEO_TOKENS: dict[str, str] = {}
_INSTAGRAM_OAUTH_STATES: set[str] = set()


def _revive_projects_from_disk() -> None:
    """Reabre os projetos salvos em output/web_projects/ ao iniciar.

    O projeto é criado "pronto" (timeline restaurada): o usuário recarrega
    a página e continua de onde parou, mesmo depois de o servidor cair.
    """
    if not PROJECTS_DIR.is_dir():
        return
    settings = Settings.load()
    for folder in sorted(PROJECTS_DIR.iterdir()):
        meta = folder / "project.json"
        if not meta.is_file() or folder.name in PROJECTS:
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            video_path = Path(data.get("video_path", ""))
            if not video_path.exists():
                continue
            manager, image_manager, music_manager, pack_manager = (
                _new_managers(settings)
            )
            state = ProjectState(
                id=folder.name,
                video_path=video_path,
                settings=settings,
                manager=manager,
                image_manager=image_manager,
                music_manager=music_manager,
                pack_manager=pack_manager,
            )
            state.timeline = data.get("timeline", {}) or {}
            state.caption = data.get("caption", "")
            state.hashtags = data.get("hashtags", []) or []
            if state.timeline:
                state.status = "ready"
                # contexto mínimo para re-renderizar sem nova análise:
                # _apply_timeline_to_ctx reconstrói o plano a partir da
                # timeline salva (cortes, legendas, áudio, palavras…)
                from core.edit_plan import EditPlan as _EditPlan
                from core.models import Transcript as _Transcript
                from core.pipeline import PipelineContext as _Ctx

                tl = state.timeline
                ctx = _Ctx(
                    input_path=video_path, settings=state.settings
                )
                ctx.edit_plan = _EditPlan(
                    duration=float(
                        (tl.get("video") or {}).get("duration", 0.0)
                    ),
                    source="reaberto do disco",
                )
                ctx.transcript = _Transcript(
                    duration=float(
                        (tl.get("video") or {}).get("duration", 0.0)
                    )
                )
                state.ctx = ctx
            PROJECTS[state.id] = state
        except Exception as exc:
            logger.warning("Projeto %s não pôde ser reaberto: %s", folder.name, exc)


def _new_managers(settings: Settings) -> tuple[
    ProviderManager, ImageProviderManager, MusicManager, PackManager
]:
    manager = _PROVIDER_MANAGER  # configuração de IA compartilhada
    image_manager = ImageProviderManager()
    pack_manager = PackManager(settings)
    music_folders = [settings.music_dir] if settings.music_dir else []
    music_folders += [str(f) for f in pack_manager.music_folders()]
    music_manager = MusicManager(music_folders)
    return manager, image_manager, music_manager, pack_manager


# ----------------------------------------------------------------------
# Modelos de request
# ----------------------------------------------------------------------


class TimelineUpdate(BaseModel):
    """Patch da timeline enviado pelo frontend."""

    cuts: list[dict] = []
    zooms: list[dict] = []
    transition: dict = {}
    captions: list[dict] = []
    callouts: list[dict] = []
    keywords: list[dict] = []
    layouts: list[dict] = []
    hook: dict = {}
    music: dict = {}
    sfx: list[dict] = []
    caption_style: str = ""
    caption_scale: float = 0.0


class ProviderUpdate(BaseModel):
    """Configuração de um provedor de IA (chave, modelo, ativo)."""

    provider_id: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    active: bool = False


class InstagramConnect(BaseModel):
    """Token de acesso do Meta para conectar a conta Instagram."""

    access_token: str


class InstagramPublish(BaseModel):
    """Pedido de publicação no Instagram."""

    access_token: str
    ig_user_id: str
    media_type: str  # REELS, STORIES, VIDEO
    caption: str
    token_kind: str = "facebook"  # "instagram" (login direto) ou "facebook"


# Gerenciador global de provedores: a configuração (API key, modelo,
# ativo) é compartilhada por todos os projetos e sobrevive a reinícios.
_PROVIDER_MANAGER = ProviderManager()


def _providers_payload() -> dict:
    return {
        "providers": _PROVIDER_MANAGER.describe_providers(),
        "active": _PROVIDER_MANAGER.active_id(),
    }


@app.get("/api/providers")
def list_providers() -> dict:
    """Lista os provedores de IA disponíveis (nunca expõe a API key)."""
    return _providers_payload()


@app.put("/api/providers")
def update_provider(req: ProviderUpdate) -> dict:
    """Salva API key/modelo/base_url e/ou marca o provedor como ativo."""
    m = _PROVIDER_MANAGER
    if req.provider_id not in m.provider_ids:
        raise HTTPException(404, f"Provedor desconhecido: {req.provider_id}")
    if req.api_key:
        m.set_api_key(req.provider_id, req.api_key.strip())
    if req.model is not None:
        m.set_model(req.provider_id, req.model.strip())
    if req.base_url is not None:
        m.set_base_url(req.provider_id, req.base_url)
    if req.active:
        m.set_active(req.provider_id)
    return {"ok": True, **_providers_payload()}


# ----------------------------------------------------------------------
# Conversões timeline (JSON) <-> core
# ----------------------------------------------------------------------


def _group_captions(
    transcript: Transcript, max_words: int, max_duration: float
) -> list[dict]:
    """Agrupa palavras em blocos de legenda para o preview/editar."""
    chunks: list[dict] = []
    current: list = []

    def flush() -> None:
        if not current:
            return
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "text": w.text}
            for w in current
        ]
        chunks.append(
            {
                "id": f"k{len(chunks) + 1:04d}",
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": " ".join(w["text"] for w in words),
                "words": words,
            }
        )
        current.clear()

    for w in transcript.words:
        if current:
            span = w.end - current[0].start
            gap = w.start - current[-1].end
            if len(current) >= max_words or span >= max_duration or gap > 0.6:
                flush()
        current.append(w)
    flush()
    return chunks


def _short_reason(exc: BaseException) -> str:
    """Resumo de uma linha do motivo de a IA ter falhado."""
    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    low = msg.lower()
    if "credit balance" in low:
        return "sem créditos na conta do provedor"
    if "no module named" in low:
        return "pacote do provedor não instalado"
    if "authentication" in low or "401" in msg:
        return "chave de API inválida"
    return (msg[:80] or "erro desconhecido")


def _timeline_from_ctx(ctx: PipelineContext) -> dict:
    """Monta o estado da timeline a partir do contexto do pipeline."""
    assert ctx.transcript is not None and ctx.edit_plan is not None
    settings = ctx.settings
    captions = _group_captions(
        ctx.transcript,
        max_words=settings.max_words_per_chunk,
        max_duration=settings.max_chunk_duration,
    )
    callouts = [
        {
            "id": f"o{i + 1:04d}",
            "start": round(m.start, 3),
            "end": round(m.end, 3),
            "text": (m.callout_text or m.text or m.prompt).strip()[:40],
        }
        for i, m in enumerate(ctx.illustrations)
        if m.kind != "none"
    ]
    keywords = [
        {
            "id": f"w{i + 1:04d}",
            "start": round(k.start, 3),
            "end": round(k.end, 3),
            "text": k.word,
            "style": k.style,
            "x": round(k.x, 4),
            "y": round(k.y, 4),
            "scale": round(k.scale, 3),
        }
        for i, k in enumerate(ctx.edit_plan.keywords)
    ]
    layouts = [
        {
            "id": f"l{i + 1:04d}",
            "start": round(l.start, 3),
            "end": round(l.end, 3),
            "side": l.side,
            "title": l.title,
            "steps": list(l.steps),
            "stepImages": list(l.step_images),
        }
        for i, l in enumerate(ctx.edit_plan.layouts)
    ]
    info = None
    try:
        from core.video_processor import VideoProcessor

        info = VideoProcessor().probe(ctx.input_path)
    except Exception:  # pragma: no cover - fallback seguro
        info = None
    timeline = {
        "video": {
            "path": str(ctx.input_path),
            "duration": round(ctx.edit_plan.duration, 3),
            "width": info.width if info else 1080,
            "height": info.height if info else 1920,
        },
        "cuts": [
            {
                "id": f"c{i + 1:04d}",
                "start": round(c.start, 3),
                "end": round(c.end, 3),
                "reason": c.reason,
                "transition": (
                    {
                        "type": c.transition_type,
                        "duration": round(c.transition_duration, 3),
                    }
                    if c.transition_type
                    else None
                ),
            }
            for i, c in enumerate(ctx.edit_plan.cuts)
        ],
        "zooms": [
            {
                "id": f"z{i + 1:04d}",
                "start": round(z.start, 3),
                "end": round(z.end, 3),
                "intensity": z.intensity,
            }
            for i, z in enumerate(ctx.edit_plan.zooms)
        ],
        "transition": {
            "type": ctx.edit_plan.transition_type,
            "duration": ctx.edit_plan.transition_duration,
        },
        "captions": captions,
        "callouts": callouts,
        "keywords": keywords,
        "layouts": layouts,
        "hook": (
            ctx.edit_plan.hook.to_dict()
            if ctx.edit_plan.hook
            else {
                "id": "hook-1",
                "enabled": False,
                "text": "",
                "start": 0,
                "end": 2.5,
                "color": "#FFFFFF",
                "highlight_color": "#FF3B30",
                "effect": "pulse",
                "scale": 1.0,
                "x": 0.5,
                "y": 0.3,
                "font_family": "Anton",
            }
        ),
        "caption_style": settings.caption_style,
        "caption_scale": float(getattr(settings, "caption_scale", 1.0)),
        "music": {
            "path": str(ctx.audio_plan.music_path)
            if ctx.audio_plan and ctx.audio_plan.music_path
            else None,
            "label": ctx.audio_plan.music_label if ctx.audio_plan else "",
            "volume": ctx.audio_plan.music_volume if ctx.audio_plan else 0.25,
        },
        "sfx": (
            [
                {
                    "id": f"s{i + 1:04d}",
                    "kind": e.kind,
                    "timestamp": round(e.timestamp, 3),
                    "path": str(e.path) if e.path else None,
                    "origin": e.origin,
                }
                for i, e in enumerate(ctx.audio_plan.sfx)
            ]
            if ctx.audio_plan
            else []
        ),
        "warning": ctx.analysis_warning or None,
    }
    return timeline


def _apply_timeline_to_ctx(state: ProjectState) -> None:
    """Escreve a timeline editada de volta no PipelineContext (para o render)."""
    tl = state.timeline
    ctx = state.ctx
    if ctx is None:
        return
    assert ctx.edit_plan is not None

    # estilo/tamanho da legenda escolhidos na UI
    cs = tl.get("caption_style")
    if cs:
        ctx.settings.caption_style = str(cs)
    sc = tl.get("caption_scale")
    if sc:
        ctx.settings.caption_scale = max(0.4, min(2.0, float(sc)))

    ctx.edit_plan = EditPlan(
        cuts=[
            Cut(
                start=float(c["start"]),
                end=float(c["end"]),
                reason=str(c.get("reason", "")),
                transition_type=str(
                    (c.get("transition") or {}).get("type", "") or ""
                ),
                transition_duration=float(
                    (c.get("transition") or {}).get("duration", 0) or 0
                ),
            )
            for c in tl.get("cuts", [])
        ],
        zooms=[
            ZoomEffect(
                start=float(z["start"]),
                end=float(z["end"]),
                intensity=float(z.get("intensity", 0.15)),
            )
            for z in tl.get("zooms", [])
        ],
        transition_type=str(
            tl.get("transition", {}).get("type", ctx.edit_plan.transition_type)
        ),
        transition_duration=float(
            tl.get("transition", {}).get(
                "duration", ctx.edit_plan.transition_duration
            )
        ),
        duration=ctx.edit_plan.duration,
    )

    # gancho editável no início do vídeo
    hook_data = tl.get("hook")
    if hook_data:
        from core.edit_plan import HookBlock

        ctx.edit_plan.hook = HookBlock(
            id=str(hook_data.get("id", "hook-1")),
            enabled=bool(hook_data.get("enabled", False)),
            text=str(hook_data.get("text", "")),
            start=float(hook_data.get("start", 0.0)),
            end=float(hook_data.get("end", 2.5)),
            color=str(hook_data.get("color", "#FFFFFF")),
            highlight_color=str(hook_data.get("highlight_color", "#FF3B30")),
            effect=str(hook_data.get("effect", "pulse")),
            scale=float(hook_data.get("scale", 1.0)),
            x=float(hook_data.get("x", 0.5)),
            y=float(hook_data.get("y", 0.3)),
            font_family=str(hook_data.get("font_family", "Anton")),
        )
    else:
        ctx.edit_plan.hook = None

    # call-outs editados pelo usuário
    ctx.illustrations = [
        IllustrationMoment(
            start=float(o["start"]),
            end=float(o["end"]),
            text=str(o.get("text", "")),
            kind="callout",
            callout_text=str(o.get("text", "")),
        )
        for o in tl.get("callouts", [])
        if float(o.get("end", 0)) > float(o.get("start", 0))
    ]

    # palavras-chave editadas pelo usuário (texto/timing/efeito/posição)
    from core.edit_plan import KeywordPop

    ctx.edit_plan.keywords = [
        KeywordPop(
            start=float(k["start"]),
            end=float(k["end"]),
            word=str(k.get("text", "")).strip(),
            style=str(k.get("style", "") or ""),
            x=float(k.get("x", 0.5)),
            y=float(k.get("y", -1.0)),
            scale=float(k.get("scale", 1.0)),
        )
        for k in tl.get("keywords", [])
        if float(k.get("end", 0)) > float(k.get("start", 0))
        and str(k.get("text", "")).strip()
    ]

    # call-out que repete palavra-chave no mesmo momento sai fora
    # (projetos antigos já salvos com duplicata também ficam limpos)
    if ctx.edit_plan.keywords:
        from core.illustration_plan import dedupe_callouts_vs_keywords

        ctx.illustrations = dedupe_callouts_vs_keywords(
            ctx.illustrations, ctx.edit_plan.keywords
        )

    # cenas de layout editadas pelo usuário (timing/lado/título/passos)
    from core.edit_plan import LayoutScene

    ctx.edit_plan.layouts = [
        LayoutScene(
            start=float(l["start"]),
            end=float(l["end"]),
            side="right" if str(l.get("side", "left")) == "right" else "left",
            title=str(l.get("title", "EXPLICAÇÃO") or "EXPLICAÇÃO"),
            steps=[str(s) for s in (l.get("steps") or []) if str(s).strip()],
            step_images=[
                str(p) for p in (l.get("stepImages") or [])
            ],
        )
        for l in tl.get("layouts", [])
        if float(l.get("end", 0)) - float(l.get("start", 0)) >= 1.0
    ]

    # legendas editadas pelo usuário → reconstrói a transcrição usada no render
    captions = tl.get("captions", [])
    if captions and ctx.transcript is not None:
        from core.models import Word

        new_words: list[Word] = []
        for chunk in captions:
            words = chunk.get("words") or []
            text = str(chunk.get("text", "")).strip()
            joined = " ".join(w.get("text", "") for w in words).strip()
            if text and text != joined:
                # texto editado manualmente: uma "palavra" cobre o bloco
                new_words.append(
                    Word(
                        text=text,
                        start=float(chunk["start"]),
                        end=float(chunk["end"]),
                    )
                )
            else:
                new_words.extend(
                    Word(
                        text=str(w["text"]),
                        start=float(w["start"]),
                        end=float(w["end"]),
                    )
                    for w in words
                )
        if new_words:
            ctx.transcript.words = new_words

    if ctx.audio_plan is not None:
        from core.audio_plan import SfxEvent

        music = tl.get("music", {})
        music_path = music.get("path")
        ctx.audio_plan.music_path = Path(music_path) if music_path else None
        ctx.audio_plan.music_label = str(music.get("label", ""))
        ctx.audio_plan.music_volume = float(music.get("volume", 0.25))
        sfx: list[SfxEvent] = []
        auto_whoosh_count = 0
        for item in tl.get("sfx", []):
            kind = str(item.get("kind", "whoosh"))
            path = Path(item["path"]) if item.get("path") else None
            origin = str(item.get("origin", ""))
            # "manual" = o usuário escolheu na biblioteca: nunca é limitado.
            # Projetos antigos (sem origin) são tratados como automáticos
            # para que o limite de dois whooshes continue valendo neles.
            manual = origin == "manual" or path is not None
            if kind == "whoosh" and not manual:
                if auto_whoosh_count >= 2:
                    continue
                auto_whoosh_count += 1
            sfx.append(
                SfxEvent(
                    kind=kind,
                    timestamp=float(item.get("timestamp", 0)),
                    origin=origin or "manual",
                    path=path,
                )
            )
        ctx.audio_plan.sfx = sfx


def _save_project_json(state: ProjectState) -> None:
    folder = PROJECTS_DIR / state.id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.json").write_text(
        json.dumps(
            {
                "id": state.id,
                "video_path": str(state.video_path),
                "status": state.status,
                "timeline": state.timeline,
                "caption": state.caption,
                "hashtags": state.hashtags,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ----------------------------------------------------------------------
# Workers em background
# ----------------------------------------------------------------------


def _suggest_step_images(pack_manager, ctx) -> None:
    """Sugere ícones do pack para os cartões da cena de explicação.

    Casa palavras do texto do cartão com o nome dos arquivos do pack
    (emojis/elementos/overlays). Conservador: sem casamento, sem ícone.
    """
    if pack_manager is None or not ctx.edit_plan.layouts:
        return
    icon_cats = ("emojis", "elementos", "overlays")
    catalog: list[str] = []
    for cat in icon_cats:
        catalog += [
            str(i.path) for i in pack_manager.category_items(cat)
        ]
    if not catalog:
        return

    def tokens(text: str) -> set[str]:
        import re as _re

        return {
            t for t in _re.findall(r"[a-zà-ÿ0-9]{3,}", text.lower())
        }

    for sc in ctx.edit_plan.layouts:
        if sc.step_images:
            continue  # usuário já escolheu; não sobrescreve
        images: list[str] = []
        for s in sc.steps:
            st = tokens(s)
            match = next(
                (
                    p
                    for p in catalog
                    if tokens(Path(p).stem) & st
                ),
                "",
            )
            images.append(match)
        if any(images):
            sc.step_images = images


def _diag_tick(
    phase: str, project_id: str, overall: float, step: str, msg: str
) -> None:
    """Registra o último ponto de progresso + RAM em arquivo.

    Se o processo for morto por falta de memória (OOM kill), o arquivo
    fica parado exatamente no ponto da morte — permite diagnosticar a
    etapa que estourou sem precisar dos logs do provedor.
    """
    rss_mb = None
    try:
        with open("/proc/self/statm") as f:
            rss_mb = int(f.read().split()[1]) * 4096 / 1_000_000
    except Exception:
        pass
    try:
        (DATA_DIR / "diag_last.json").write_text(
            json.dumps(
                {
                    "phase": phase,
                    "project": project_id,
                    "step": step,
                    "msg": msg,
                    "overall": round(overall, 3),
                    "rss_mb": round(rss_mb, 1) if rss_mb else None,
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass
    logger.info(
        "[diag] %s | %s | %.0f%% | %.1f MB | %s",
        phase,
        step,
        overall * 100,
        rss_mb or 0,
        msg,
    )


def _analyze_worker(state: ProjectState) -> None:
    state.status = "analyzing"
    state.emit("status", status=state.status)

    def progress(overall: float, step: str, msg: str) -> None:
        _diag_tick("analise", state.id, overall, step, msg)
        state.emit_progress(overall, step, msg)

    try:
        ctx = PipelineContext(input_path=state.video_path, settings=state.settings)
        state.ctx = ctx
        build_analysis_pipeline(
            state.manager,
            state.image_manager,
            state.music_manager,
            state.pack_manager,
        ).run(ctx, progress)
        _suggest_step_images(state.pack_manager, ctx)
        state.timeline = _timeline_from_ctx(ctx)

        # Gera legenda + hashtags para publicação social (grátis: heurística local)
        if ctx.transcript is not None:
            try:
                from ai.caption_generator import generate_caption

                generated = generate_caption(
                    ctx.transcript.text,
                    provider_manager=state.manager,
                    platform="reels",
                    language=getattr(ctx.transcript, "language", "pt"),
                )
                state.caption = generated.caption
                state.hashtags = generated.hashtags
                logger.info("Legenda gerada: %d hashtags", len(state.hashtags))
            except Exception as exc:
                logger.warning("Falha ao gerar legenda: %s", exc)

        state.status = "ready"
        state.emit("timeline", timeline=state.timeline)
    except Exception as exc:
        logger.exception("Análise falhou")
        state.error = str(exc)
        state.status = "failed"
        state.emit("error", message=str(exc))
    state.emit("status", status=state.status)
    _save_project_json(state)


def _render_worker(state: ProjectState) -> None:
    state.status = "rendering"
    state.emit("status", status=state.status)

    def progress(overall: float, step: str, msg: str) -> None:
        _diag_tick("render", state.id, overall, step, msg)
        state.emit_progress(overall, step, msg)

    try:
        # re-render: intermediários do temp já foram limpos; refaz do início
        state.ctx.edited_path = None
        _apply_timeline_to_ctx(state)
        assert state.ctx is not None
        build_render_pipeline().run(state.ctx, progress)
        state.status = "done"
        assert state.ctx.output_path is not None
        # Gera token para URL pública temporária (usada pelo Meta ao publicar)
        state.public_token = secrets.token_urlsafe(24)
        _PUBLIC_VIDEO_TOKENS[state.public_token] = state.id
        state.emit("done", output=str(state.ctx.output_path))
    except Exception as exc:
        logger.exception("Render falhou")
        state.error = str(exc)
        state.status = "failed"
        state.emit("error", message=str(exc))
    state.emit("status", status=state.status)
    _save_project_json(state)


# ----------------------------------------------------------------------
# Rotas
# ----------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    import os

    from core.video_processor import low_ram_mode
    from config.settings import _detect_ram_gb

    return {
        "ok": True,
        "version": "2-light",
        "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7],
        "low_ram_mode": low_ram_mode(),
        "ram_gb": round(_detect_ram_gb(), 2),
    }


@app.get("/api/debug/last-diag")
def last_diag() -> dict:
    """Último ponto de progresso + RAM antes de uma queda do processo."""
    try:
        return json.loads((DATA_DIR / "diag_last.json").read_text())
    except Exception:
        return {"ok": False, "detail": "nenhum diagnóstico registrado ainda"}


@app.post("/api/projects")
def create_project(payload: dict) -> dict:
    video_path = Path(str(payload.get("path", ""))).expanduser()
    if not video_path.exists() or video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(400, "Arquivo de vídeo inválido.")
    settings = Settings.load()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tm = TemplateManager()
    for t in tm.list_templates():
        ensure_caption_preset(t)
    manager, image_manager, music_manager, pack_manager = _new_managers(settings)
    project = ProjectState(
        id=uuid.uuid4().hex[:12],
        video_path=video_path,
        settings=settings,
        manager=manager,
        image_manager=image_manager,
        music_manager=music_manager,
        pack_manager=pack_manager,
    )
    PROJECTS[project.id] = project
    return {
        "id": project.id,
        "name": video_path.name,
        "status": project.status,
        "settings": {
            "output_format": settings.output_format,
            "whisper_model": settings.whisper_model,
            "caption_style": settings.caption_style,
        },
    }


@app.post("/api/projects/{project_id}/analyze")
def analyze(project_id: str) -> dict:
    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")
    if state.status in ("analyzing",):
        raise HTTPException(409, "Análise já em andamento.")
    threading.Thread(
        target=_analyze_worker, args=(state,), daemon=True
    ).start()
    return {"ok": True}


@app.get("/api/projects/{project_id}/events")
def events(project_id: str):
    """Stream de progresso (SSE) da análise/render."""
    from sse_starlette.sse import EventSourceResponse

    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")

    def gen():
        while True:
            try:
                event = state.events.get(timeout=15)
            except queue.Empty:
                yield {"event": "ping", "data": "{}"}
                continue
            kind = event.pop("kind", "message")
            yield {
                "event": kind,
                "data": json.dumps(event, ensure_ascii=False),
            }
            if kind in ("done", "error"):
                break

    return EventSourceResponse(gen(), media_type="text/event-stream")


@app.get("/api/projects/{project_id}/timeline")
def get_timeline(project_id: str) -> dict:
    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")
    return {"status": state.status, "timeline": state.timeline}


@app.get("/api/projects/{project_id}/caption")
def get_caption(project_id: str) -> dict:
    """Retorna a legenda + hashtags geradas para publicação social."""
    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")
    return {
        "caption": state.caption,
        "hashtags": state.hashtags,
        "full_text": f"{state.caption}\n\n{' '.join(state.hashtags)}".strip(),
    }


# ----------------------------------------------------------------------
# Instagram (Graph API do Meta)
# ----------------------------------------------------------------------


@app.get("/api/instagram/oauth/start")
def instagram_oauth_start() -> dict:
    """Cria o link seguro de login para conectar o Instagram.

    Prioriza o fluxo "API do Instagram com login do Instagram"
    (INSTAGRAM_APP_ID); sem ele, cai para o login via Facebook/Meta.
    """
    ig_app_id = os.environ.get("INSTAGRAM_APP_ID", "").strip()
    meta_app_id = os.environ.get("META_APP_ID", "").strip()
    if not ig_app_id and not meta_app_id:
        raise HTTPException(
            503,
            "Login automático ainda não foi configurado pelo administrador "
            "(INSTAGRAM_APP_ID ou META_APP_ID). Use o modo alternativo ou "
            "avise o administrador.",
        )
    from config.settings import get_public_base_url

    state = secrets.token_urlsafe(24)
    _INSTAGRAM_OAUTH_STATES.add(state)
    redirect_uri = f"{get_public_base_url()}/api/instagram/oauth/callback"

    if ig_app_id:
        query = urlencode(
            {
                "client_id": ig_app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": "instagram_business_basic,instagram_business_content_publish",
                "response_type": "code",
            }
        )
        return {
            "url": f"https://www.instagram.com/oauth/authorize?{query}",
            "redirect_uri": redirect_uri,
            "flow": "instagram",
        }

    query = urlencode(
        {
            "client_id": meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement",
            "response_type": "code",
        }
    )
    return {
        "url": f"https://www.facebook.com/v20.0/dialog/oauth?{query}",
        "redirect_uri": redirect_uri,
        "flow": "facebook",
    }


@app.get("/api/instagram/oauth/callback", response_class=HTMLResponse)
def instagram_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Troca o código do login e devolve o token à janela que iniciou."""
    if state not in _INSTAGRAM_OAUTH_STATES:
        return HTMLResponse("Login inválido ou expirado.", status_code=400)
    _INSTAGRAM_OAUTH_STATES.discard(state)
    if error or not code:
        return HTMLResponse(
            "<script>window.opener?.postMessage({type:'instagram-oauth-error',"
            "message:'Login cancelado.'}, '*'); window.close();</script>"
        )
    ig_app_id = os.environ.get("INSTAGRAM_APP_ID", "").strip()
    ig_app_secret = os.environ.get("INSTAGRAM_APP_SECRET", "").strip()
    use_instagram_flow = bool(ig_app_id and ig_app_secret)
    if use_instagram_flow:
        meta_app_id = meta_secret = ""
    else:
        meta_app_id = os.environ.get("META_APP_ID", "").strip()
        meta_secret = os.environ.get("META_APP_SECRET", "").strip()
        if not meta_app_id or not meta_secret:
            return HTMLResponse("Login automático não configurado.", status_code=503)

    from config.settings import get_public_base_url
    from social.instagram import (
        InstagramError,
        connect_account,
        connect_account_instagram,
    )
    import requests

    redirect_uri = f"{get_public_base_url()}/api/instagram/oauth/callback"
    try:
        if use_instagram_flow:
            # Fluxo do login direto do Instagram
            response = requests.post(
                "https://api.instagram.com/oauth/access_token",
                data={
                    "client_id": ig_app_id,
                    "client_secret": ig_app_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            access_token = data["access_token"]
            ig_user_id = str(data.get("user_id", ""))

            # Troca por token de longa duração (60 dias)
            long_resp = requests.get(
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": ig_app_secret,
                    "access_token": access_token,
                },
                timeout=20,
            )
            if long_resp.ok:
                access_token = long_resp.json().get("access_token", access_token)

            account = connect_account_instagram(access_token)
            if not account.ig_user_id:
                account.ig_user_id = ig_user_id
            token_kind = "instagram"
        else:
            # Fluxo via Facebook/Meta (alternativo)
            response = requests.get(
                "https://graph.facebook.com/v20.0/oauth/access_token",
                params={
                    "client_id": meta_app_id,
                    "client_secret": meta_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
                timeout=20,
            )
            response.raise_for_status()
            access_token = response.json()["access_token"]
            account = connect_account(access_token)
            token_kind = "facebook"

        payload = json.dumps(
            {
                "type": "instagram-oauth-success",
                "access_token": access_token,
                "ig_user_id": account.ig_user_id,
                "username": account.username,
                "token_kind": token_kind,
            }
        )
        return HTMLResponse(
            f"<script>window.opener?.postMessage({payload}, '*'); window.close();</script>"
        )
    except (requests.RequestException, KeyError, InstagramError) as exc:
        logger.warning("Falha no callback OAuth do Instagram: %s", exc)
        detail = getattr(exc, "message", None) or str(exc)
        message = json.dumps(
            {"type": "instagram-oauth-error", "message": f"Não foi possível conectar a conta: {detail}"}
        )
        return HTMLResponse(
            f"<p>Falha ao conectar o Instagram: {detail}</p>"
            f"<script>window.opener?.postMessage({message}, '*');</script>"
        )
    except Exception as exc:
        logger.exception("Erro inesperado no callback OAuth do Instagram")
        detail = str(exc)
        message = json.dumps(
            {"type": "instagram-oauth-error", "message": f"Erro inesperado ao conectar: {detail}"}
        )
        return HTMLResponse(
            f"<p>Falha ao conectar o Instagram: {detail}</p>"
            f"<script>window.opener?.postMessage({message}, '*');</script>"
        )


@app.post("/api/instagram/connect")
def instagram_connect(body: InstagramConnect) -> dict:
    """Valida o token do Meta e retorna a conta Instagram vinculada."""
    from social.instagram import InstagramError, connect_account

    try:
        account = connect_account(body.access_token)
        return {
            "connected": True,
            "ig_user_id": account.ig_user_id,
            "username": account.username,
            "page_name": account.page_name,
        }
    except InstagramError as exc:
        raise HTTPException(400, exc.message)
    except Exception as exc:
        logger.exception("Falha ao conectar Instagram")
        raise HTTPException(500, f"Erro ao conectar: {exc}")


@app.post("/api/projects/{project_id}/instagram/publish")
def instagram_publish(project_id: str, body: InstagramPublish) -> dict:
    """Publica o vídeo renderizado no Instagram (Reels/Story/Feed)."""
    from social.instagram import (
        InstagramError,
        publish_video,
        GRAPH_BASE,
        INSTAGRAM_GRAPH_BASE,
    )

    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")
    if state.status != "done" or state.ctx is None or state.ctx.output_path is None:
        raise HTTPException(400, "Renderize o vídeo antes de publicar.")
    if not state.public_token or state.public_token not in _PUBLIC_VIDEO_TOKENS:
        raise HTTPException(400, "URL pública expirada. Renderize novamente.")

    # URL pública que o Meta baixa (mesma origem do servidor)
    from config.settings import get_public_base_url

    video_url = f"{get_public_base_url()}/api/public-video/{state.public_token}"
    try:
        result = publish_video(
            ig_user_id=body.ig_user_id,
            video_url=video_url,
            caption=body.caption,
            media_type=body.media_type,
            access_token=body.access_token,
            graph_base=(
                INSTAGRAM_GRAPH_BASE
                if body.token_kind == "instagram"
                else GRAPH_BASE
            ),
        )
        return {
            "ok": True,
            "media_id": result.get("media_id"),
            "permalink": result.get("permalink"),
        }
    except InstagramError as exc:
        raise HTTPException(400, exc.message)
    except Exception as exc:
        logger.exception("Falha ao publicar no Instagram")
        raise HTTPException(500, f"Erro ao publicar: {exc}")


@app.get("/api/public-video/{token}")
def public_video(token: str):
    """Vídeo renderizado acessível por URL pública temporária.

    O Meta baixa o vídeo desta URL ao criar o container de mídia.
    O token é aleatório e regenerado a cada render.
    """
    project_id = _PUBLIC_VIDEO_TOKENS.get(token)
    if project_id is None:
        raise HTTPException(404, "Token inválido ou expirado.")
    state = PROJECTS.get(project_id)
    if state is None or state.ctx is None or state.ctx.output_path is None:
        raise HTTPException(404, "Vídeo não disponível.")
    return FileResponse(
        state.ctx.output_path,
        media_type="video/mp4",
        filename=f"{project_id}.mp4",
    )


@app.put("/api/projects/{project_id}/timeline")
def put_timeline(project_id: str, update: TimelineUpdate) -> dict:
    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")
    tl = state.timeline
    tl["cuts"] = update.cuts
    tl["zooms"] = update.zooms
    if update.transition:
        tl["transition"] = update.transition
    tl["captions"] = update.captions
    tl["callouts"] = update.callouts
    tl["keywords"] = update.keywords
    tl["layouts"] = update.layouts
    if update.hook:
        tl["hook"] = update.hook
    if update.music:
        tl["music"] = update.music
    tl["sfx"] = update.sfx
    if update.caption_style:
        tl["caption_style"] = update.caption_style
    if update.caption_scale > 0:
        tl["caption_scale"] = update.caption_scale
    _save_project_json(state)
    return {"ok": True}


@app.get("/api/caption-styles")
def caption_styles() -> dict:
    """Presets de estilo de legenda disponíveis (espelho de core/caption_styles)."""
    from core.caption_styles import PRESETS

    styles = []
    for sid, s in PRESETS.items():
        styles.append(
            {
                "id": sid,
                "font_family": s.font_name,
                "font_size_vertical": s.font_size_vertical,
                "font_size_horizontal": s.font_size_horizontal,
                "primary_color": s.primary_color,
                "highlight_color": s.highlight_color,
                "outline": s.outline,
                "uppercase": s.uppercase,
            }
        )
    return {"styles": styles}


@app.get("/api/projects/{project_id}/video")
def video_stream(project_id: str):
    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")
    if state.ctx is not None and state.ctx.edited_path is not None:
        return FileResponse(state.ctx.edited_path, media_type="video/mp4")
    return FileResponse(state.video_path, media_type="video/mp4")


@app.post("/api/projects/{project_id}/render")
def render(project_id: str) -> dict:
    state = PROJECTS.get(project_id)
    if state is None:
        raise HTTPException(404, "Projeto não encontrado.")
    if state.status not in ("ready", "done"):
        raise HTTPException(409, "Análise pendente ou render em andamento.")
    threading.Thread(
        target=_render_worker, args=(state,), daemon=True
    ).start()
    return {"ok": True}


@app.get("/api/projects/{project_id}/output")
def output(project_id: str):
    state = PROJECTS.get(project_id)
    if state is None or state.ctx is None or state.ctx.output_path is None:
        raise HTTPException(404, "Render ainda não disponível.")
    return FileResponse(
        state.ctx.output_path,
        media_type="video/mp4",
        filename=f"auto_editor_{project_id}.mp4",
    )


@app.post("/api/upload")
async def upload_video(file: UploadFile) -> dict:
    """Recebe um vídeo enviado pelo navegador (arrastar ou escolher arquivo)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(400, "Formato não suportado. Use mp4, mov, mkv, webm, avi ou m4v.")
    upload_dir = OUTPUT_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid.uuid4().hex[:12]}{suffix}"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(4 * 1024 * 1024):
            out.write(chunk)
            size += len(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Arquivo vazio.")
    return {"path": str(dest), "name": file.filename, "size": size}


MUSIC_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".opus"}


def _user_music_dir() -> Path:
    d = OUTPUT_DIR / "uploads" / "music"
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.post("/api/upload/music")
async def upload_music(file: UploadFile) -> dict:
    """Recebe uma música enviada pelo usuário (ex.: galeria do celular)."""
    name = Path(file.filename or "musica").stem or "musica"
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in MUSIC_EXTENSIONS:
        suffix = ".mp3"
    dest = _user_music_dir() / f"{uuid.uuid4().hex[:12]}{suffix}"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(4 * 1024 * 1024):
            out.write(chunk)
            size += len(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Arquivo vazio.")
    return {"path": str(dest), "label": name}


@app.get("/api/pack/file")
def pack_file(path: str):
    """Serve uma imagem do pack (ícones dos cartões da cena)."""
    state = next(iter(PROJECTS.values()), None)
    if state is None:
        raise HTTPException(404, "Nenhum projeto aberto.")
    p = Path(path)
    allowed = {
        str(i.path)
        for cat in ("emojis", "elementos", "overlays", "gifs", "light_leaks")
        for i in state.pack_manager.category_items(cat)
    }
    if str(p) not in allowed or not p.is_file():
        raise HTTPException(404, "Arquivo fora do pack ou inexistente.")
    return FileResponse(p)


@app.get("/api/files")
def list_files(dir: str = "") -> dict:
    """Navegador de arquivos local (para escolher o vídeo na interface)."""
    import os

    base = Path(dir or Path.home()).expanduser()
    if not base.exists() or not base.is_dir():
        raise HTTPException(400, "Pasta não encontrada.")
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except PermissionError:
        raise HTTPException(403, "Sem permissão nesta pasta.")
    dirs = [
        e.name for e in entries if e.is_dir() and not e.name.startswith(".")
    ][:200]
    videos = [
        e.name
        for e in entries
        if e.is_file() and e.suffix.lower() in VIDEO_EXTENSIONS
    ][:200]
    drives = []
    if os.name == "nt" and base.parent == base:
        import string

        drives = [
            f"{c}:\\" for c in string.ascii_uppercase if Path(f"{c}:\\").exists()
        ]
    return {
        "current": str(base),
        "parent": str(base.parent) if base.parent != base else None,
        "drives": drives,
        "dirs": dirs,
        "videos": videos,
    }


@app.get("/api/library")
def library() -> dict:
    """Biblioteca: trilhas padrão + pack externo por categoria."""
    from core.audio_plan import SFX_KINDS

    state = next(iter(PROJECTS.values()), None)
    music_items: list[dict] = []
    sfx_items: list[dict] = []
    pack: dict[str, list[dict]] = {}
    if state is not None:
        settings = state.settings
        pm = state.pack_manager
        # música: trilhas embutidas + pack
        assets_music = Path("assets/music")
        if assets_music.exists():
            for f in sorted(assets_music.glob("*.mp3")) + sorted(
                assets_music.glob("*.wav")
            ):
                music_items.append({"path": str(f), "label": f.stem, "origin": "padrão"})
        for folder in pm.music_folders():
            if folder.exists():
                for f in sorted(folder.glob("*")):
                    if f.suffix.lower() in {".mp3", ".wav", ".ogg"}:
                        music_items.append(
                            {"path": str(f), "label": f.stem, "origin": "pack"}
                        )
        # sfx: os sintetizados (sempre disponíveis) + os do pack
        _SFX_LABELS = {
            "whoosh": "Whoosh (transição)",
            "ding": "Ding (destaque)",
            "impact": "Impact (impacto)",
            "pop": "Pop (estalo)",
        }
        for kind in SFX_KINDS:
            sfx_items.append(
                {
                    "path": "",
                    "label": kind,
                    "origin": "sintetizado",
                    "display": _SFX_LABELS.get(kind, kind),
                }
            )
        for item in pm.category_items("sfx"):
            sfx_items.append(
                {"path": str(item.path), "label": item.name, "origin": "pack"}
            )
        # categorias visuais
        for cat in ("overlays", "transicoes", "emojis", "gifs", "light_leaks", "elementos"):
            items = pm.category_items(cat)
            pack[cat] = [
                {"path": str(i.path), "label": i.name} for i in items[:80]
            ]
    # músicas enviadas pelo usuário (galeria do celular) primeiro
    user_dir = _user_music_dir()
    user_items = [
        {"path": str(f), "label": f.stem, "origin": "do celular"}
        for f in sorted(user_dir.glob("*"))
        if f.suffix.lower() in MUSIC_EXTENSIONS
    ]
    return {"music": user_items + music_items, "sfx": sfx_items, "pack": pack}


@app.get("/api/transitions")
def transitions() -> dict:
    return {"types": TRANSITION_TYPES}


# ----------------------------------------------------------------------
# Política de Privacidade (exigida pela Análise do Meta / App Review)
# ----------------------------------------------------------------------

_PRIVACY_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Política de Privacidade — KalBix Editor</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; max-width: 720px;
         margin: 0 auto; padding: 24px; color: #1a1a2e; line-height: 1.6; }
  h1 { font-size: 1.6rem; } h2 { font-size: 1.15rem; margin-top: 1.6em; }
  .updated { color: #666; font-size: .9rem; }
</style>
</head>
<body>
<h1>Política de Privacidade — KalBix Editor</h1>
<p class="updated">Última atualização: fevereiro de 2026</p>

<h2>1. O que somos</h2>
<p>O KalBix Editor é uma ferramenta web de edição automática de vídeos que permite
ao usuário cortar pausas, adicionar legendas, efeitos e publicar o resultado
diretamente em suas próprias redes sociais (Instagram, entre outras).</p>

<h2>2. Dados que coletamos</h2>
<ul>
  <li><strong>Vídeos enviados</strong>: usados exclusivamente para gerar a edição
  solicitada pelo usuário.</li>
  <li><strong>Token de acesso do Instagram</strong>: quando o usuário conecta a
  conta, recebemos um token via OAuth oficial do Instagram. Ele é usado apenas
  para publicar o conteúdo que o próprio usuário solicitou e não é compartilhado
  com terceiros.</li>
  <li><strong>Legendas e textos gerados</strong>: derivados da transcrição do
  áudio do vídeo enviado, para uso do próprio usuário na publicação.</li>
</ul>

<h2>3. Como usamos os dados</h2>
<p>Os dados são usados somente para: (a) processar e renderizar a edição do vídeo;
(b) publicar no Instagram o conteúdo que o usuário autorizou; (c) gerar legendas
e hashtags sugeridas. Não vendemos, alugamos ou compartilhamos dados pessoais
com terceiros.</p>

<h2>4. Permissões do Instagram</h2>
<p>Solicitamos as permissões <code>instagram_business_basic</code> (ler perfil
profissional básico para identificar a conta conectada) e
<code>instagram_business_content_publish</code> (publicar Reels, Stories e posts
solicitados pelo usuário). Não acessamos mensagens diretas, senhas nem dados de
seguidores.</p>

<h2>5. Armazenamento e retenção</h2>
<p>Projetos e vídeos são armazenados temporariamente em nosso servidor para
permitir a edição e a publicação, e podem ser removidos quando o usuário exclui
o projeto ou após período de inatividade. O token do Instagram não é gravado em
disco no servidor.</p>

<h2>6. Contato</h2>
<p>Dúvidas sobre esta política ou solicitação de exclusão de dados:
<strong>contato@kalbix.com</strong>.</p>
</body>
</html>"""


@app.get("/politica-de-privacidade", response_class=HTMLResponse)
def privacy_policy() -> HTMLResponse:
    return HTMLResponse(_PRIVACY_HTML)


# ----------------------------------------------------------------------
# Frontend estático (web/dist), se existir
# ----------------------------------------------------------------------

_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
else:  # pragma: no cover - durante desenvolvimento

    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "message": "Frontend não compilado. Rode: cd web && npm install && npm run build"
            }
        )


# Reabre projetos salvos (após todas as definições do módulo)
_revive_projects_from_disk()
