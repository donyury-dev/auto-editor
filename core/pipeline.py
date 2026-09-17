"""Orquestrador do Auto Editor: sequência de etapas com progresso agregado.

Cada fase do produto (cortes, música, imagens...) se torna um PipelineStep
novo, sem alterar as demais etapas nem a UI.
"""

from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from config.settings import TEMP_DIR, OutputFormat, Settings
from core.exporter import Exporter
from core.models import Transcript
from core.subtitle_engine import SubtitleEngine
from core.transcriber import TranscriptionEngine
from core.video_processor import VideoProcessor, resolve_target_resolution

logger = logging.getLogger(__name__)

StepProgressFn = Callable[[float, str], None]
PipelineProgressFn = Callable[[float, str, str], None]


@dataclass
class PipelineContext:
    """Estado compartilhado entre as etapas de uma execução."""

    input_path: Path
    settings: Settings
    work_dir: Path = field(
        default_factory=lambda: TEMP_DIR
        / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    transcript: Optional[Transcript] = None
    ass_path: Optional[Path] = None
    rendered_path: Optional[Path] = None
    output_path: Optional[Path] = None


class PipelineStep(ABC):
    """Uma etapa do pipeline. `weight` define o peso no progresso total."""

    name: str = "etapa"
    weight: float = 1.0

    @abstractmethod
    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        """Executa a etapa. Levanta exceção em caso de falha."""


class TranscribeStep(PipelineStep):
    name = "Transcrição"
    weight = 0.5

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        engine = TranscriptionEngine(model_size=ctx.settings.whisper_model)
        ctx.transcript = engine.transcribe(ctx.input_path, progress=progress)
        if not ctx.transcript.words:
            raise RuntimeError(
                "Nenhuma fala detectada no vídeo. Verifique o áudio de entrada."
            )


class BuildSubtitlesStep(PipelineStep):
    name = "Legendas"
    weight = 0.05

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        progress(0.1, "gerando legendas estilo viral…")
        assert ctx.transcript is not None
        info = VideoProcessor().probe(ctx.input_path)
        target_w, target_h = resolve_target_resolution(
            ctx.settings.output_format, info
        )
        engine = SubtitleEngine(
            max_words=ctx.settings.max_words_per_chunk,
            max_duration=ctx.settings.max_chunk_duration,
        )
        ctx.ass_path = ctx.work_dir / "captions.ass"
        engine.write_ass(ctx.transcript, ctx.ass_path, target_w, target_h)
        progress(1.0, "legendas geradas")


class RenderStep(PipelineStep):
    name = "Renderização"
    weight = 0.4

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.ass_path is not None
        ctx.rendered_path = ctx.work_dir / "render.mp4"
        VideoProcessor().render(
            ctx.input_path,
            ctx.ass_path,
            ctx.rendered_path,
            ctx.settings.output_format,
            progress=progress,
        )


class ExportStep(PipelineStep):
    name = "Exportação"
    weight = 0.05

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.rendered_path is not None
        progress(0.5, "salvando vídeo final…")
        ctx.output_path = Exporter().export(
            ctx.rendered_path, ctx.input_path.stem, ctx.settings.output_format
        )
        assert ctx.output_path is not None
        progress(1.0, f"concluído: {ctx.output_path.name}")


class Pipeline:
    """Executa a sequência de etapas agregando o progresso total."""

    def __init__(self, steps: list[PipelineStep]) -> None:
        self.steps = steps
        self._total_weight = sum(s.weight for s in steps) or 1.0

    def run(
        self,
        ctx: PipelineContext,
        progress: Optional[PipelineProgressFn] = None,
    ) -> PipelineContext:
        ctx.work_dir.mkdir(parents=True, exist_ok=True)
        done = 0.0
        step: PipelineStep = self.steps[0]
        try:
            for step in self.steps:
                logger.info("Etapa iniciada: %s", step.name)

                def step_progress(
                    frac: float,
                    msg: str = "",
                    _weight: float = step.weight,
                    _done: float = done,
                    _name: str = step.name,
                ) -> None:
                    if progress is None:
                        return
                    clamped = max(0.0, min(1.0, frac))
                    overall = (_done + _weight * clamped) / self._total_weight
                    progress(min(1.0, overall), _name, msg)

                step.run(ctx, step_progress)
                done += step.weight
                if progress:
                    progress(
                        min(1.0, done / self._total_weight),
                        step.name,
                        "etapa concluída",
                    )
        except Exception:
            logger.exception("Pipeline falhou na etapa: %s", step.name)
            raise
        else:
            shutil.rmtree(ctx.work_dir, ignore_errors=True)
            logger.info("Pipeline concluído com sucesso.")
        return ctx


def build_default_pipeline() -> Pipeline:
    """Pipeline da Fase 1 (MVP): transcrever -> legendas -> render -> export."""
    return Pipeline(
        [
            TranscribeStep(),
            BuildSubtitlesStep(),
            RenderStep(),
            ExportStep(),
        ]
    )
