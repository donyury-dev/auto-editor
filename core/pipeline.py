"""Orquestrador do Auto Editor: sequência de etapas com progresso agregado.

Cada fase do produto (cortes, música, imagens...) se torna um PipelineStep
novo, sem alterar as demais etapas nem a UI.
"""

from __future__ import annotations

import logging
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from config.settings import TEMP_DIR, OutputFormat, Settings
from audio.mixer import AudioMixer
from audio.music_manager import MusicManager
from core.audio_plan import (
    AudioPlan,
    remap_sfx,
    suggest_sfx_from_plan,
)
from core.caption_styles import get_caption_style
from core.edit_plan import (
    EditPlan,
    snap_cuts_to_word_gaps,
    validate_plan,
)
from core.exporter import Exporter
from core.illustration_plan import (
    IllustrationMoment,
    moments_to_json,
    validate_illustrations,
)
from core.models import Transcript, Word
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
    # Fase 2: plano de edição (pós-revisão) e vídeo já editado
    edit_plan: Optional[EditPlan] = None
    edited_path: Optional[Path] = None
    # Fase Ilustrações: momentos sugeridos (pós-revisão) com imagens locais
    illustrations: list[IllustrationMoment] = field(default_factory=list)
    # Fase 4: plano de áudio (música + SFX) — pós-revisão
    audio_plan: Optional[AudioPlan] = None


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
        # Posição vertical: % da altura a partir da base, configurável pelo
        # usuário (sobrepõe as margens padrão do preset).
        pct = max(1, min(95, ctx.settings.caption_vertical_position))
        margin_v = int(target_h * pct / 100)
        style = replace(
            get_caption_style(ctx.settings.caption_style),
            margin_v_vertical=margin_v,
            margin_v_horizontal=margin_v,
        )
        engine = SubtitleEngine(
            style=style,
            max_words=ctx.settings.max_words_per_chunk,
            max_duration=ctx.settings.max_chunk_duration,
        )
        ctx.ass_path = ctx.work_dir / "captions.ass"
        engine.write_ass(ctx.transcript, ctx.ass_path, target_w, target_h)
        progress(1.0, "legendas geradas")


class BuildEditPlanStep(PipelineStep):
    """Gera o plano de edição — DEPOIS disso a UI abre a tela de revisão."""

    name = "Plano de edição"
    weight = 0.1

    def __init__(self, provider_manager=None) -> None:
        self._manager = provider_manager

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.transcript is not None
        progress(0.2, "analisando conteúdo…")
        duration = ctx.transcript.duration or (
            ctx.transcript.words[-1].end if ctx.transcript.words else 0.0
        )
        segments = [
            {"start": w.start, "end": w.end, "text": w.text}
            for w in ctx.transcript.words
        ]
        text = ctx.transcript.text

        provider = None
        source = "heurística local"
        try:
            if self._manager is not None:
                provider = self._manager.get_active()
        except Exception as exc:
            logger.info("Provedor de IA indisponível (%s); usando heurística.", exc)
        if provider is None:
            from ai.heuristic_provider import HeuristicProvider

            provider = HeuristicProvider()
        else:
            source = provider.label

        progress(0.5, f"sugerindo cortes e zooms ({source})…")
        raw = provider.suggest_edit_plan(
            text, segments, duration, language=ctx.transcript.language
        )
        plan = EditPlan.from_dict(
            {**raw, "source": source, "duration": duration}
        )
        # cortes da IA podem cair no meio de palavras: ajusta p/ bordas
        plan.cuts = snap_cuts_to_word_gaps(plan.cuts, ctx.transcript.words)
        plan = validate_plan(plan)

        ctx.edit_plan = plan
        plan.save(ctx.work_dir / "edit_plan.json")
        progress(
            1.0,
            f"{len(plan.cuts)} corte(s), {len(plan.zooms)} zoom(s) sugeridos",
        )


class ApplyEditsStep(PipelineStep):
    """Aplica o plano APROVADO: cortes + zooms + transições.

    Também remapeia a transcrição para a nova linha do tempo, para as
    legendas continuarem sincronizadas.
    """

    name = "Edição"
    weight = 0.4

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.transcript is not None
        plan = ctx.edit_plan
        if plan is None or (not plan.cuts and not plan.zooms):
            progress(1.0, "nenhuma edição aprovada — usando original")
            return

        processor = VideoProcessor()
        info = processor.probe(ctx.input_path)
        if plan.duration <= 0:
            plan.duration = info.duration

        ctx.edited_path = ctx.work_dir / "edited.mp4"
        processor.apply_edit_plan(
            ctx.input_path,
            plan,
            info,
            ctx.settings.output_format,
            ctx.edited_path,
            progress=progress,
        )

        # remapeia a transcrição para a linha do tempo pós-cortes
        # (palavras inteiramente dentro de um corte são descartadas)
        remapped = []
        for w in ctx.transcript.words:
            inside_cut = any(
                c.start <= w.start and w.end <= c.end for c in plan.cuts
            )
            if inside_cut:
                continue
            remapped.append(
                Word(
                    text=w.text,
                    start=plan.remap_time(w.start),
                    end=plan.remap_time(w.end),
                )
            )
        ctx.transcript = Transcript(
            words=remapped,
            language=ctx.transcript.language,
            duration=plan.final_duration,
        )
        progress(1.0, f"edição aplicada: {plan.final_duration:.1f}s de vídeo")


class BuildIllustrationPlanStep(PipelineStep):
    """Sugere momentos de B-roll e busca/gera as imagens (com cache).

    Roda na ANÁLISE, antes da tela de revisão — o usuário vê thumbnails
    e aprova/troca/remove antes de qualquer render. Falhas de rede/key
    degradam para placeholder local; a etapa nunca quebra.
    """

    name = "Ilustrações"
    weight = 0.25

    def __init__(self, provider_manager=None, image_manager=None) -> None:
        self._manager = provider_manager
        self._image_manager = image_manager

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.transcript is not None
        duration = ctx.transcript.duration or (
            ctx.transcript.words[-1].end if ctx.transcript.words else 0.0
        )
        segments = [
            {"start": w.start, "end": w.end, "text": w.text}
            for w in ctx.transcript.words
        ]
        density = ctx.settings.illustration_density_s

        provider = None
        source = "heurística local"
        try:
            if self._manager is not None:
                provider = self._manager.get_active()
        except Exception as exc:
            logger.info("Provedor de IA indisponível (%s); heurística.", exc)
        if provider is None:
            from ai.heuristic_provider import HeuristicProvider

            provider = HeuristicProvider()
        else:
            source = provider.label

        progress(0.2, f"detectando momentos visuais ({source})…")
        try:
            raw = provider.suggest_illustration_moments(
                ctx.transcript.text,
                segments,
                duration,
                language=ctx.transcript.language,
                density_s=density,
            )
        except Exception as exc:
            # IA de linguagem pode falhar (rede/quota): segue sem ilustrações
            logger.warning("Sugestão de ilustrações falhou: %s", exc)
            raw = []

        moments = [
            IllustrationMoment(
                start=float(m.get("start", 0)),
                end=float(m.get("end", 0)),
                text=str(m.get("text", "")),
                prompt=str(m.get("prompt", "")),
            )
            for m in raw
            if isinstance(m, dict)
        ]
        moments = validate_illustrations(
            moments, duration, ctx.transcript.words, density_s=density
        )

        # busca/gera imagens (cache por prompt; fallback local)
        image_provider_id = ctx.settings.illustration_provider
        total = len(moments)
        for i, m in enumerate(moments):
            progress(
                0.3 + 0.6 * (i / max(1, total)),
                f"buscando imagem {i + 1}/{total}: “{m.prompt[:40]}…”",
            )
            if self._image_manager is not None:
                try:
                    path = self._image_manager.fetch_cached(
                        image_provider_id, m.prompt
                    )
                    m.image_path = path
                    m.source = image_provider_id
                except Exception as exc:
                    logger.warning("Imagem falhou (%s): %s", m.prompt, exc)

        ctx.illustrations = moments
        moments_to_json(moments, ctx.work_dir / "illustrations.json")
        progress(
            1.0,
            f"{len(moments)} ilustração(ões) sugeridas"
            + ("" if not moments else " — revise na próxima tela"),
        )


class ApplyIllustrationsStep(PipelineStep):
    """Aplica as ilustrações APROVADAS sobre o vídeo editado.

    Os timestamps (linha original) são remapeados pelo plano de edição;
    momentos que caírem dentro de cortes são descartados.
    """

    name = "Ilustrações"
    weight = 0.15

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        approved = [m for m in ctx.illustrations if m.image_path]
        if not approved:
            progress(1.0, "nenhuma ilustração aprovada")
            return

        plan = ctx.edit_plan
        source = ctx.edited_path or ctx.input_path
        processor = VideoProcessor()
        info = processor.probe(source)

        remapped: list[IllustrationMoment] = []
        for m in approved:
            if plan is not None and plan.cuts:
                if any(
                    c.start <= m.start and m.end <= c.end for c in plan.cuts
                ):
                    continue  # fala inteira removida
                start = plan.remap_time(m.start)
                end = plan.remap_time(m.end)
            else:
                start, end = m.start, m.end
            if end - start < 0.5:
                continue
            remapped.append(
                IllustrationMoment(
                    start=start,
                    end=end,
                    text=m.text,
                    prompt=m.prompt,
                    image_path=m.image_path,
                    source=m.source,
                )
            )

        if not remapped:
            progress(1.0, "ilustrações fora da linha do tempo; nada a aplicar")
            return

        out = ctx.work_dir / "illustrated.mp4"
        processor.apply_illustrations(
            source,
            remapped,
            info,
            ctx.settings.output_format,
            out,
            progress=progress,
        )
        ctx.edited_path = out


class BuildAudioPlanStep(PipelineStep):
    """Sugere o plano de áudio (trilha por clima + SFX) para revisão.

    O clima vem do provedor de IA ativo (Claude) ou da heurística local
    (ritmo da fala). A trilha é escolhida na biblioteca local do usuário;
    sem trilhas cadastradas, segue sem música — nunca quebra.
    """

    name = "Áudio"
    weight = 0.1

    def __init__(self, provider_manager=None, music_manager=None) -> None:
        self._manager = provider_manager
        self._music_manager = music_manager

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.transcript is not None and ctx.edit_plan is not None
        segments = [
            {"start": w.start, "end": w.end, "text": w.text}
            for w in ctx.transcript.words
        ]

        provider = None
        source = "heurística local"
        try:
            if self._manager is not None:
                provider = self._manager.get_active()
        except Exception as exc:
            logger.info("Provedor de IA indisponível (%s); heurística.", exc)
        if provider is None:
            from ai.heuristic_provider import HeuristicProvider

            provider = HeuristicProvider()
        else:
            source = provider.label

        progress(0.3, f"sugerindo clima da trilha ({source})…")
        try:
            mood = provider.suggest_music_mood(
                ctx.transcript.text, segments
            )
        except Exception as exc:
            logger.warning("Sugestão de clima falhou (%s); neutro.", exc)
            from ai.heuristic_provider import HeuristicProvider

            mood = HeuristicProvider().suggest_music_mood(
                ctx.transcript.text, segments
            )

        track = None
        if self._music_manager is not None:
            progress(0.6, "escolhendo trilha na biblioteca…")
            track = self._music_manager.pick(mood.mood, mood.energy)
        if track is None:
            logger.info("Biblioteca de músicas vazia; seguindo sem trilha.")

        sfx = (
            suggest_sfx_from_plan(ctx.edit_plan, ctx.illustrations)
            if ctx.settings.sfx_enabled
            else []
        )

        ctx.audio_plan = AudioPlan(
            mood=mood.mood,
            energy=mood.energy,
            music_path=track.path if track else None,
            music_label=track.label if track else "",
            music_volume=ctx.settings.music_volume,
            normalize_voice=ctx.settings.voice_normalize,
            sfx=sfx,
        )
        ctx.audio_plan.save(ctx.work_dir / "audio_plan.json")
        progress(
            1.0,
            f"clima “{mood.mood}” • "
            + (f"trilha: {track.path.name}" if track else "sem trilha")
            + f" • {len(sfx)} efeito(s) — revise na próxima tela",
        )


class ApplyAudioStep(PipelineStep):
    """Aplica o plano de áudio APROVADO: loudnorm + trilha com ducking + SFX.

    Os timestamps dos efeitos são remapeados pelo plano de edição; a voz
    é normalizada ANTES do ducking (exigência do projeto).
    """

    name = "Áudio"
    weight = 0.15

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        plan = ctx.audio_plan
        if plan is None:
            progress(1.0, "sem plano de áudio")
            return
        if (
            plan.music_path is None
            and not plan.sfx
            and not plan.normalize_voice
        ):
            progress(1.0, "áudio inalterado (nada aprovado)")
            return

        source = ctx.edited_path or ctx.input_path
        processor = VideoProcessor()
        info = processor.probe(source)

        plan.sfx = remap_sfx(plan.sfx, ctx.edit_plan)
        out = ctx.work_dir / "mixed.mp4"
        AudioMixer().apply(
            source,
            plan,
            info,
            out,
            progress=progress,
        )
        ctx.edited_path = out


class RenderStep(PipelineStep):
    name = "Renderização"
    weight = 0.4

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.ass_path is not None
        ctx.rendered_path = ctx.work_dir / "render.mp4"
        source = ctx.edited_path or ctx.input_path
        VideoProcessor().render(
            source,
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
        # Limpa sessões antigas (de falhas passadas ou do app ser fechado
        # no meio), evitando que temp/ cresça indefinidamente.
        cleanup_stale_sessions()
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


def cleanup_stale_sessions(
    max_age_hours: float = 24.0, base_dir: Optional[Path] = None
) -> int:
    """Remove sessões de temp/ mais antigas que `max_age_hours`.

    A sessão da execução atual é apagada ao final do pipeline com sucesso
    (shutil.rmtree no Pipeline.run); este limpeza cobre os casos de falha
    (diretório mantido para debug) e de encerramento forçado do app.
    Retorna quantas sessões foram removidas.
    """
    base_dir = Path(base_dir or TEMP_DIR)
    if not base_dir.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for entry in base_dir.iterdir():
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError as exc:
            logger.debug("Não foi possível limpar %s: %s", entry, exc)
    if removed:
        logger.info("Limpeza de temp/: %d sessão(ões) antiga(s) removida(s).", removed)
    return removed


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


def build_analysis_pipeline(
    provider_manager=None,
    image_manager=None,
    music_manager=None,
) -> Pipeline:
    """Análise: transcrever + planos de edição/ilustrações/áudio (revisão)."""
    return Pipeline(
        [
            TranscribeStep(),
            BuildEditPlanStep(provider_manager),
            BuildIllustrationPlanStep(provider_manager, image_manager),
            BuildAudioPlanStep(provider_manager, music_manager),
        ]
    )


def build_render_pipeline() -> Pipeline:
    """Render: aplicar aprovados -> áudio -> legendas -> render -> export."""
    return Pipeline(
        [
            ApplyEditsStep(),
            ApplyIllustrationsStep(),
            ApplyAudioStep(),
            BuildSubtitlesStep(),
            RenderStep(),
            ExportStep(),
        ]
    )
