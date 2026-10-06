"""Diagnóstico: análise + render do vídeo do usuário fora do servidor.

Reproduz exatamente o que server/app.py faz, mas em processo único com
traceback completo no stdout — imune a reinício do uvicorn.
"""

import logging
import sys
import time
import traceback
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

from server.app import _apply_timeline_to_ctx, _new_managers, ProjectState  # noqa: E402
from core.pipeline import PipelineContext, build_analysis_pipeline, build_render_pipeline  # noqa: E402
from config.settings import Settings  # noqa: E402

VIDEO = Path("/workspace/quero-que-voc-me/output/uploads/15ba1a14ff49.mp4")


def main() -> None:
    settings = Settings()
    mgr, img_mgr, mus_mgr, pack_mgr = _new_managers(settings)
    state = ProjectState(
        id="diag",
        video_path=VIDEO,
        settings=settings,
        manager=mgr,
        image_manager=img_mgr,
        music_manager=mus_mgr,
        pack_manager=pack_mgr,
    )
    ctx = PipelineContext(input_path=VIDEO, settings=settings)
    state.ctx = ctx

    t0 = time.time()
    print("=== ANALISE ===", flush=True)
    build_analysis_pipeline(mgr, img_mgr, mus_mgr, pack_mgr).run(
        ctx, lambda o, s, m: print(f"[{o:5.1%}] {s}: {m}", flush=True)
    )
    print(f"analise ok em {time.time() - t0:.0f}s", flush=True)

    # timeline padrão (o que o servidor entregaria) + render
    state.timeline = __import__(
        "server.app", fromlist=["_timeline_from_ctx"]
    )._timeline_from_ctx(ctx)
    _apply_timeline_to_ctx(state)

    t1 = time.time()
    print("=== RENDER ===", flush=True)
    build_render_pipeline().run(
        ctx, lambda o, s, m: print(f"[{o:5.1%}] {s}: {m}", flush=True)
    )
    print(f"render ok em {time.time() - t1:.0f}s", flush=True)
    print("OUTPUT:", ctx.output_path, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
