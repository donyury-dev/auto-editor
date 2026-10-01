"""Teste E2E do fluxo completo usado na v1.0.3."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# FFmpeg de desenvolvimento (static_ffmpeg) não está no PATH do container
try:
    import static_ffmpeg

    _ffmpeg_dev = Path(static_ffmpeg.__file__).resolve().parent / "bin"
    for _arch in _ffmpeg_dev.iterdir():
        if _arch.is_dir():
            os.environ["PATH"] = f"{_arch}{os.pathsep}{os.environ.get('PATH', '')}"
            break
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Garante import relativo à raiz do projeto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.provider_manager import ProviderManager
from audio.music_manager import MusicManager
from config.settings import OutputFormat, Settings
from core.pipeline import PipelineContext, build_analysis_pipeline, build_render_pipeline
from core.templates import TemplateManager, apply_template
from images.manager import ImageProviderManager


def progress(overall: float, step: str, msg: str) -> None:
    print(f"[{overall*100:5.1f}%] {step}: {msg}")


def main() -> int:
    input_path = Path(".verdent/uploads/teste de video.mp4")
    if not input_path.exists():
        print(f"Vídeo de teste não encontrado: {input_path}")
        return 1

    settings = Settings.load()
    manager = TemplateManager()
    template = manager.get("motivacional")
    if template is None:
        print("Template motivacional não encontrado")
        return 1
    apply_template(settings, template)
    settings.active_template_id = template.id
    settings.output_format = OutputFormat.VERTICAL
    settings.illustration_provider = "local"
    # Fase 7: pack externo de teste (mesma estrutura do CapCut Pack)
    settings.pack_root = "/tmp/pack-test"
    settings.save()

    print(f"Aplicando template: {template.name}")
    print(f"Configurações: transition={settings.transition_type}, "
          f"silence_gap={settings.silence_gap_s}, "
          f"zoom_intensity={settings.zoom_intensity}, "
          f"max_zooms={settings.max_zooms}")

    ctx = PipelineContext(input_path=input_path, settings=settings)

    provider_manager = ProviderManager()
    image_manager = ImageProviderManager()
    music_manager = MusicManager([settings.music_dir])

    print("\n--- ANÁLISE ---")
    from core.pack_manager import PackManager

    pack_manager = PackManager(settings)
    build_analysis_pipeline(
        provider_manager, image_manager, music_manager, pack_manager
    ).run(ctx, progress)

    print("\nResultado da análise:")
    print(f"  Cortes: {len(ctx.edit_plan.cuts)}")
    print(f"  Zooms: {len(ctx.edit_plan.zooms)}")
    print(f"  Destaques: {len(ctx.illustrations)}")
    print(f"  Efeitos: {len(ctx.audio_plan.sfx) if ctx.audio_plan else 0}")
    print(f"  Pack: {len(ctx.pack_suggestions)} sugestão(ões)")
    for s in ctx.pack_suggestions:
        print(f"    - [{s.kind}] {s.path.name} @ {s.start:.1f}s ({s.reason})")

    # Aprova tudo automaticamente para o teste
    print("\n--- APROVANDO TUDO ---")
    for cut in ctx.edit_plan.cuts:
        cut.approved = True
    for zoom in ctx.edit_plan.zooms:
        zoom.approved = True
    for ill in ctx.illustrations:
        ill.approved = True
    for s in ctx.pack_suggestions:
        s.approved = True

    print("\n--- RENDER ---")
    build_render_pipeline().run(ctx, progress)

    print(f"\nOK: vídeo gerado em {ctx.output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
