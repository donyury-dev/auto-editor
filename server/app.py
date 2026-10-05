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
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

    def emit(self, kind: str, **data: Any) -> None:
        payload = {"kind": kind, **data}
        self.events.put(payload)

    def emit_progress(self, overall: float, step: str, msg: str) -> None:
        self.emit("progress", overall=round(overall, 4), step=step, msg=msg)


PROJECTS: dict[str, ProjectState] = {}


def _new_managers(settings: Settings) -> tuple[
    ProviderManager, ImageProviderManager, MusicManager, PackManager
]:
    manager = ProviderManager()
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
    music: dict = {}
    sfx: list[dict] = []
    caption_style: str = ""
    caption_scale: float = 0.0


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
                }
                for i, e in enumerate(ctx.audio_plan.sfx)
            ]
            if ctx.audio_plan
            else []
        ),
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
        ctx.audio_plan.sfx = [
            SfxEvent(
                kind=str(s.get("kind", "whoosh")),
                timestamp=float(s.get("timestamp", 0)),
                origin=str(s.get("origin", "manual")),
                path=Path(s["path"]) if s.get("path") else None,
            )
            for s in tl.get("sfx", [])
        ]


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
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ----------------------------------------------------------------------
# Workers em background
# ----------------------------------------------------------------------


def _analyze_worker(state: ProjectState) -> None:
    state.status = "analyzing"
    state.emit("status", status=state.status)

    def progress(overall: float, step: str, msg: str) -> None:
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
        state.timeline = _timeline_from_ctx(ctx)
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
        state.emit_progress(overall, step, msg)

    try:
        _apply_timeline_to_ctx(state)
        assert state.ctx is not None
        build_render_pipeline().run(state.ctx, progress)
        state.status = "done"
        assert state.ctx.output_path is not None
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
    return {"ok": True}


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
        # sfx do pack
        for item in pm.category_items("sfx"):
            sfx_items.append(
                {"path": str(item.path), "label": item.name, "origin": "pack"}
            )
        # categorias visuais
        for cat in ("overlays", "transicoes", "emojis", "gifs", "light_leaks"):
            items = pm.category_items(cat)
            pack[cat] = [
                {"path": str(i.path), "label": i.name} for i in items[:80]
            ]
    return {"music": music_items, "sfx": sfx_items, "pack": pack}


@app.get("/api/transitions")
def transitions() -> dict:
    return {"types": TRANSITION_TYPES}


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
