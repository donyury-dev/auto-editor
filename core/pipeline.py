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
    SfxEvent,
    remap_sfx,
    suggest_sfx_from_plan,
)
from core.caption_styles import get_caption_style
from core.edit_plan import (
    EditPlan,
    KeywordPop,
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
from core.pack_manager import (
    PackManager,
    PackSuggestion,
    suggestions_to_json,
)
from core.subtitle_engine import SubtitleEngine
from core.transcriber import TranscriptionEngine
from core.video_processor import VideoProcessor, resolve_target_resolution

logger = logging.getLogger(__name__)

StepProgressFn = Callable[[float, str], None]
PipelineProgressFn = Callable[[float, str, str], None]


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
    if "not_found" in low or "404" in msg:
        return "modelo indisponível para esta chave"
    return (msg[:80] or "erro desconhecido")


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
    # Fase 7: sugestões do pack externo (pós-revisão) e LUT aprovado
    pack_suggestions: list[PackSuggestion] = field(default_factory=list)
    lut_path: Optional[Path] = None
    # Edição estilo anúncio: instantes de mudança de cena (vazio se a
    # detecção falhar — nunca bloqueia a análise)
    scene_times: list[float] = field(default_factory=list)
    # Direção por corte (ai/director.py): SFX extras sugeridos pela IA,
    # mesclados na etapa de áudio
    direction_sfx: list[SfxEvent] = field(default_factory=list)
    # Aviso não-fatal da análise (ex.: IA indisponível, caiu pra heurística)
    analysis_warning: str = ""


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
        from config.settings import resolve_whisper_model

        engine = TranscriptionEngine(
            model_size=resolve_whisper_model(ctx.settings.whisper_model)
        )
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
        # Cenas de layout já têm painel + palavra sincronizada (como no
        # vídeo modelo): a legenda embaixo atravessaria o card — remove
        # as falas dentro dessas cenas da legenda.
        transcript = ctx.transcript
        plan = ctx.edit_plan
        if plan is not None and plan.layouts:
            ranges = [
                (plan.remap_time(sc.start), plan.remap_time(sc.end))
                for sc in plan.layouts
            ]
            kept = [
                w for w in transcript.words
                if not any(w.end > s and w.start < e for s, e in ranges)
            ]
            if kept and len(kept) < len(transcript.words):
                transcript = replace(
                    transcript,
                    words=kept,
                    duration=kept[-1].end,
                )
        # Posição vertical: % da altura a partir da base, configurável pelo
        # usuário (sobrepõe as margens padrão do preset).
        pct = max(1, min(95, ctx.settings.caption_vertical_position))
        margin_v = int(target_h * pct / 100)
        scale = max(0.4, min(2.0, float(getattr(ctx.settings, "caption_scale", 1.0))))
        base = get_caption_style(ctx.settings.caption_style)
        style = replace(
            base,
            font_size_vertical=max(20, int(base.font_size_vertical * scale)),
            font_size_horizontal=max(16, int(base.font_size_horizontal * scale)),
            margin_v_vertical=margin_v,
            margin_v_horizontal=margin_v,
        )
        engine = SubtitleEngine(
            style=style,
            max_words=ctx.settings.max_words_per_chunk,
            max_duration=ctx.settings.max_chunk_duration,
            context_lines=ctx.settings.caption_context_lines,
        )
        ctx.ass_path = ctx.work_dir / "captions.ass"
        engine.write_ass(transcript, ctx.ass_path, target_w, target_h)
        progress(1.0, "legendas geradas")


class SceneDetectStep(PipelineStep):
    """Detecta mudanças de cena para alinhar cortes ao ritmo visual."""

    name = "Cenas"
    weight = 0.05

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        from core.scene_detect import detect_scene_changes

        progress(0.3, "procurando mudanças de cenário…")
        try:
            ctx.scene_times = detect_scene_changes(ctx.input_path)
        except Exception as exc:  # pragma: no cover - defesa
            logger.warning("Detecção de cena falhou: %s", exc)
            ctx.scene_times = []
        progress(
            1.0,
            f"{len(ctx.scene_times)} mudança(s) de cenário detectada(s)",
        )


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

        # Aplica os parâmetros de ritmo do template ativo (Settings)
        if hasattr(provider, "configure_from_settings"):
            provider.configure_from_settings(ctx.settings)

        progress(0.5, f"sugerindo cortes e zooms ({source})…")
        try:
            raw = provider.suggest_edit_plan(
                text, segments, duration, language=ctx.transcript.language
            )
        except Exception as exc:
            # IA indisponível (sem créditos, rede, módulo faltando…):
            # nunca aborta a análise — cai pra heurística e avisa.
            logger.warning("Provedor de IA falhou (%s); heurística.", exc)
            from ai.heuristic_provider import (
                HeuristicProvider as _FallbackProvider,
            )

            provider = _FallbackProvider()
            if hasattr(provider, "configure_from_settings"):
                provider.configure_from_settings(ctx.settings)
            source = provider.label
            ctx.analysis_warning = (
                f"IA indisponível ({_short_reason(exc)}); edição feita "
                "com a heurística local."
            )
            progress(0.5, f"IA indisponível — usando {source}…")
            raw = provider.suggest_edit_plan(
                text, segments, duration, language=ctx.transcript.language
            )
        plan = EditPlan.from_dict(
            {**raw, "source": source, "duration": duration}
        )
        # cortes da IA podem cair no meio de palavras: ajusta p/ bordas
        plan.cuts = snap_cuts_to_word_gaps(plan.cuts, ctx.transcript.words)
        # alinha cortes às mudanças de cena (edição estilo anúncio)
        if ctx.scene_times:
            from core.scene_detect import align_cuts_to_scenes

            plan.cuts = align_cuts_to_scenes(plan.cuts, ctx.scene_times)
        # Direção por corte: com IA ativa, a IA escolhe a transição e o
        # efeito de cada corte; sem IA, direção heurística local
        # (cortes de mudança de cenário variados, respiros secos).
        ctx.direction_sfx = []
        directed = False
        if provider is not None and source != "heurística local":
            progress(0.8, f"direção de cena ({source})…")
            try:
                raw_dir = provider.suggest_direction(
                    plan, segments, duration
                )
                if raw_dir:
                    from ai.director import apply_ai_direction

                    ctx.direction_sfx = apply_ai_direction(
                        plan, raw_dir, duration
                    )
                    directed = True
            except Exception as exc:
                logger.warning("Direção da IA falhou (%s); heurística.", exc)
        if not directed:
            from ai.director import apply_heuristic_direction

            apply_heuristic_direction(plan)
        plan = validate_plan(plan)
        # palavras-chave em pop (estilo anúncio) — só na primeira análise
        if not plan.keywords:
            from core.keyword_engine import pick_keywords

            plan.keywords = pick_keywords(
                ctx.transcript.words, duration=duration
            )
        # cenas de layout "aula" (card + painel) — só na primeira análise
        if not plan.layouts:
            from core.layout_engine import pick_layouts

            plan.layouts = pick_layouts(ctx.transcript.words, duration)

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

        from core.video_processor import low_ram_mode

        if low_ram_mode():
            # Mantém apenas os intervalos de corte. Transições e zooms
            # exigem filtros/re-encode adicionais e não fazem parte do
            # modo simples para servidores com 512 MB.
            plan = replace(
                plan,
                zooms=[],
                transition_type="corte",
                transition_duration=0.0,
                cuts=[
                    replace(
                        cut,
                        transition_type="corte",
                        transition_duration=0.0,
                    )
                    for cut in plan.cuts
                ],
            )

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

    name = "Destaques"
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
                kind=str(m.get("kind", "callout")),
                callout_text=str(
                    m.get("callout_text", "")
                    or m.get("text", "")
                    or m.get("prompt", "")
                ),
            )
            for m in raw
            if isinstance(m, dict)
        ]
        moments = validate_illustrations(
            moments, duration, ctx.transcript.words, density_s=density
        )
        # call-out que repete palavra-chave no mesmo momento sai fora
        # (o pop da palavra já cobre o efeito — sem texto duplicado)
        if ctx.edit_plan is not None and ctx.edit_plan.keywords:
            from core.illustration_plan import dedupe_callouts_vs_keywords

            moments = dedupe_callouts_vs_keywords(
                moments, ctx.edit_plan.keywords
            )

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

    name = "Destaques"
    weight = 0.15

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        # Modo leve (servidor com pouca RAM): cada overlay exige um
        # re-encode completo do vídeo — pulado para o render caber na
        # memória. Ficam os cortes, legendas e áudio.
        from core.video_processor import low_ram_mode

        if low_ram_mode():
            progress(1.0, "modo leve: destaques visuais desativados")
            return

        approved_images = [
            m for m in ctx.illustrations
            if m.kind == "image" and m.image_path
        ]
        approved_callouts = [
            m for m in ctx.illustrations
            if m.kind == "callout"
        ]
        # Cenas de layout têm card/painel próprios: overlays grandes queimados
        # antes do layout aparecem DUPLICADOS dentro do card (o recorte pega o
        # call-out já queimado). Mantém só as keywords (palavra sincronizada,
        # como no vídeo modelo).
        layout_ranges = [
            (sc.start, sc.end)
            for sc in (ctx.edit_plan.layouts if ctx.edit_plan else [])
        ]

        def _in_layout(m) -> bool:
            return any(m.start < e and s < m.end for s, e in layout_ranges)

        approved_images = [m for m in approved_images if not _in_layout(m)]
        approved_callouts = [
            m for m in approved_callouts if not _in_layout(m)
        ]
        plan = ctx.edit_plan
        source = ctx.edited_path or ctx.input_path
        processor = VideoProcessor()
        info = processor.probe(source)

        # palavras-chave (independente das ilustrações), remapeadas
        keywords: list[KeywordPop] = []
        for k in (plan.keywords if plan is not None else []):
            if not k.word.strip():
                continue
            if plan is not None and plan.cuts:
                if any(
                    c.start <= k.start and k.end <= c.end for c in plan.cuts
                ):
                    continue  # momento removido pelo corte
                start = plan.remap_time(k.start)
                end = plan.remap_time(k.end)
            else:
                start, end = k.start, k.end
            if end - start < 0.3:
                continue
            keywords.append(
                KeywordPop(
                    start=start,
                    end=end,
                    word=k.word,
                    style=k.style,
                    x=k.x,
                    y=k.y,
                    scale=k.scale,
                )
            )

        if not approved_images and not approved_callouts and not keywords:
            progress(1.0, "nenhum destaque aprovado")
            return

        remapped: list[IllustrationMoment] = []
        for m in [*approved_images, *approved_callouts]:
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
                    kind=m.kind,
                    callout_text=m.callout_text,
                )
            )

        if not remapped and not keywords:
            progress(1.0, "destaques fora da linha do tempo; nada a aplicar")
            return

        current_source = source
        images = [m for m in remapped if m.kind == "image" and m.image_path]
        if images:
            out = ctx.work_dir / "illustrated.mp4"
            processor.apply_illustrations(
                current_source,
                images,
                info,
                ctx.settings.output_format,
                out,
                progress=progress,
            )
            current_source = out

        callouts = [m for m in remapped if m.kind == "callout"]
        if callouts:
            out = ctx.work_dir / "callouts.mp4"
            callout_ass = ctx.work_dir / "callouts.ass"
            target_w, target_h = resolve_target_resolution(
                ctx.settings.output_format, info
            )
            from core.callout_engine import write_callouts_ass

            write_callouts_ass(callouts, callout_ass, target_w, target_h)
            processor.apply_callouts(
                current_source,
                callout_ass,
                info,
                ctx.settings.output_format,
                out,
                progress=progress,
            )
            current_source = out

        if keywords:
            out = ctx.work_dir / "keywords.mp4"
            kw_ass = ctx.work_dir / "keywords.ass"
            kw_w, kw_h = resolve_target_resolution(
                ctx.settings.output_format, info
            )
            from core.keyword_engine import write_keywords_ass

            write_keywords_ass(keywords, kw_ass, kw_w, kw_h)
            processor.apply_callouts(
                current_source,
                kw_ass,
                info,
                ctx.settings.output_format,
                out,
                progress=progress,
            )
            current_source = out

        # Palavras-chave atrás do apresentador: separa a pessoa do fundo
        # e a recoloca por cima do texto. Falha silenciosa = texto na frente.
        if keywords and ctx.settings.keywords_behind_person:
            try:
                from core.ffmpeg_path import get_ffmpeg
                from core.mask_engine import (
                    overlay_person_segments,
                    person_overlay_segments,
                )

                segs = person_overlay_segments(
                    current_source,
                    [(k.start, k.end) for k in keywords],
                    ctx.work_dir,
                    get_ffmpeg(),
                    progress=lambda f, m: progress(0.3 + 0.45 * f, m),
                )
                if segs:
                    progress(0.8, "recolocando você na frente do texto…")
                    out2 = ctx.work_dir / "keywords_behind.mp4"
                    overlay_person_segments(
                        current_source, segs, out2, get_ffmpeg()
                    )
                    current_source = out2
            except Exception as exc:
                logger.warning(
                    "Palavras atrás da pessoa falhou (%s); texto na frente.",
                    exc,
                )

        ctx.edited_path = current_source


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
            suggest_sfx_from_plan(
                ctx.edit_plan,
                ctx.illustrations,
                extra=ctx.direction_sfx,
            )
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
        # No modo leve, mantém apenas voz tratada e música opcional.
        # SFX geram entradas extras no filter_complex e não são necessários
        # para a edição simples.
        from core.video_processor import low_ram_mode

        if low_ram_mode():
            plan.sfx = []
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


class BuildPackSuggestionsStep(PipelineStep):
    """Fase 7: sugere uso do pack externo (IA + heurística), para revisão.

    A IA ativa (Claude/Ollama/OpenAI) recebe o índice compacto do pack;
    a heurística local complementa casando nomes de assets com a fala.
    Sem pack configurado (ou HD desconectado), a etapa só avisa —
    nunca quebra.
    """

    name = "Pack"
    weight = 0.05

    def __init__(
        self,
        provider_manager=None,
        pack_manager: PackManager | None = None,
    ) -> None:
        self._manager = provider_manager
        self._pack = pack_manager or PackManager(Settings())

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.transcript is not None and ctx.audio_plan is not None
        duration = ctx.transcript.duration or 0.0
        if not getattr(ctx.settings, "pack_root", "") and not getattr(
            ctx.settings, "pack_folders", {}
        ):
            progress(1.0, "pack externo não configurado — usando assets padrão")
            return

        progress(0.2, "indexando pack externo…")
        index = self._pack.scan()
        total = sum(len(v) for v in index.values())
        if total == 0:
            progress(
                1.0,
                "pack não encontrado (HD desconectado?) — assets padrão",
            )
            return
        missing = self._pack.missing_categories()
        if missing:
            logger.warning(
                "Categorias do pack ausentes (HD desconectado?): %s", missing
            )

        words = [
            {"start": w.start, "end": w.end, "text": w.text}
            for w in ctx.transcript.words
        ]

        suggestions: list[PackSuggestion] = []
        progress(0.5, "IA analisando o pack…")
        provider = None
        try:
            if self._manager is not None:
                provider = self._manager.get_active()
        except Exception:
            provider = None
        if provider is not None and duration > 0:
            from ai.pack_suggest import build_pack_index

            try:
                raw = provider.suggest_pack_usage(
                    ctx.transcript.text,
                    words,
                    duration,
                    pack_index=build_pack_index(self._pack.all_items()),
                    language=ctx.transcript.language,
                )
                suggestions = [
                    PackSuggestion.from_dict(d)
                    for d in raw
                    if isinstance(d, dict)
                ]
            except Exception as exc:
                logger.warning("Sugestão de pack pela IA falhou: %s", exc)

        progress(0.8, "heurística local no pack…")
        heuristic = self._pack.suggest_usages(
            words, duration, mood=ctx.audio_plan.mood
        )
        seen = {str(s.path) for s in suggestions}
        for s in heuristic:
            if str(s.path) not in seen:
                suggestions.append(s)
                seen.add(str(s.path))

        ctx.pack_suggestions = suggestions
        suggestions_to_json(suggestions, ctx.work_dir / "pack_suggestions.json")
        progress(
            1.0,
            f"{len(suggestions)} sugestão(ões) do pack "
            f"({total} assets indexados) — revise na próxima tela",
        )


class ApplyPackStep(PipelineStep):
    """Aplica as sugestões do pack APROVADAS: overlays, SFX e LUT.

    Timestamps remapeados pelo plano de edição; itens que caírem dentro
    de cortes são descartados. SFX do pack entram no AudioPlan e são
    mixados pelo ApplyAudioStep.
    """

    name = "Pack"
    weight = 0.1

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        approved = list(ctx.pack_suggestions)
        if not approved:
            progress(1.0, "nenhum item do pack aprovado")
            return

        plan = ctx.edit_plan

        def remap(start: float, end: float):
            if plan is not None and plan.cuts:
                if any(c.start <= start and end <= c.end for c in plan.cuts):
                    return None
                return plan.remap_time(start), plan.remap_time(end)
            return start, end

        overlays = []
        for s in approved:
            if s.kind == "sfx":
                continue
            times = remap(s.start, s.end)
            if times is None:
                continue
            start, end = times
            if end - start < 0.5 and s.kind != "lut":
                continue
            if s.kind == "lut":
                ctx.lut_path = s.path
            else:
                overlays.append(s)

        # SFX do pack → AudioPlan (mixados com remapeamento no ApplyAudioStep)
        if ctx.audio_plan is not None:
            for s in approved:
                if s.kind != "sfx":
                    continue
                times = remap(s.start, s.end)
                if times is None:
                    continue
                from core.audio_plan import SfxEvent

                ctx.audio_plan.sfx.append(
                    SfxEvent(
                        kind=f"pack:{s.path.stem}",
                        timestamp=times[0],
                        origin=f"pack: {s.path.name}",
                        path=s.path,
                    )
                )

        if not overlays:
            progress(1.0, "pack: sem overlays a aplicar")
            return

        source = ctx.edited_path or ctx.input_path
        processor = VideoProcessor()
        info = processor.probe(source)
        out = ctx.work_dir / "pack_overlaid.mp4"
        processor.apply_overlays(
            source,
            overlays,
            info,
            ctx.settings.output_format,
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
        lut = ctx.lut_path if ctx.lut_path and ctx.lut_path.exists() else None
        VideoProcessor().render(
            source,
            ctx.ass_path,
            ctx.rendered_path,
            ctx.settings.output_format,
            progress=progress,
            lut_path=lut,
        )


class ApplyLayoutsStep(PipelineStep):
    """Queima as cenas de layout "aula" (card + painel) no vídeo final."""

    name = "Layouts"
    weight = 0.06

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.edited_path is not None
        # Modo leve: cenas de layout são um re-encode completo extra.
        from core.video_processor import low_ram_mode

        if low_ram_mode():
            progress(1.0, "modo leve: cenas de layout desativadas")
            return
        layouts = list(ctx.edit_plan.layouts) if ctx.edit_plan else []
        if not layouts:
            progress(1.0, "sem cenas de layout")
            return

        from core.ffmpeg_path import get_ffprobe, get_ffmpeg
        from core.layout_engine import apply_layouts
        from config.settings import FONTS_DIR
        import subprocess as sp
        import json as _json

        # Lê a duração real do vídeo que receberá o overlay. Ela pode ser
        # menor que a original depois dos cortes/transições.
        probe = sp.run(
            [get_ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(ctx.edited_path)],
            check=True, capture_output=True, text=True,
        )
        output_duration = float(probe.stdout.strip())

        # Remapeia o início para a linha pós-cortes, mas preserva a duração
        # que o usuário definiu. A prévia trabalha na linha original e uma
        # cena manual pode atravessar um corte automático; remapear o fim
        # independentemente faria uma cena de 10s virar 1s no export.
        plan = ctx.edit_plan
        final: list = []
        for sc in layouts:
            start = plan.remap_time(sc.start)
            end = min(output_duration, start + sc.duration)
            if end - start >= 1.5:
                from core.edit_plan import LayoutScene

                final.append(
                    LayoutScene(
                        start=start,
                        end=end,
                        side=sc.side,
                        title=sc.title,
                        steps=sc.steps,
                        reason=sc.reason,
                    )
                )
        if not final:
            progress(1.0, "cenas de layout removidas pelos cortes")
            return

        progress(0.3, f"aplicando {len(final)} cena(s) de layout…")
        out = ctx.work_dir / "layouts.mp4"
        ctx.work_dir.mkdir(parents=True, exist_ok=True)

        # dimensões do vídeo atual
        probe = sp.run(
            [get_ffprobe(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json",
             str(ctx.edited_path)],
            check=True, capture_output=True, text=True,
        )

        dims = _json.loads(probe.stdout)["streams"][0]
        apply_layouts(
            ctx.edited_path,
            out,
            final,
            int(dims["width"]),
            int(dims["height"]),
            FONTS_DIR,
            ffmpeg_bin=get_ffmpeg(),
        )
        ctx.edited_path = out
        progress(1.0, f"{len(final)} cena(s) de layout aplicada(s)")


class ExportStep(PipelineStep):
    name = "Exportação"
    weight = 0.05

    def run(self, ctx: PipelineContext, progress: StepProgressFn) -> None:
        assert ctx.rendered_path is not None
        progress(0.5, "salvando vídeo final…")
        ctx.output_path = Exporter().export(
            ctx.rendered_path,
            ctx.input_path.stem,
            ctx.settings.output_format,
            output_dir=(
                Path(ctx.settings.output_dir)
                if getattr(ctx.settings, "output_dir", "")
                else None
            ),
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
    pack_manager=None,
) -> Pipeline:
    """Análise: transcrever + planos de edição/ilustrações/áudio/pack (revisão)."""
    return Pipeline(
        [
            TranscribeStep(),
            SceneDetectStep(),
            BuildEditPlanStep(provider_manager),
            BuildIllustrationPlanStep(provider_manager, image_manager),
            BuildAudioPlanStep(provider_manager, music_manager),
            BuildPackSuggestionsStep(provider_manager, pack_manager),
        ]
    )


def build_render_pipeline() -> Pipeline:
    """Render: aplicar aprovados -> pack -> áudio -> legendas -> render -> export."""
    # O Render Starter tem 512 MB. No modo leve, não executa etapas de
    # overlay/re-encode que não são necessárias para o resultado principal:
    # cortes, legenda, música e voz tratada. Isso evita que uma etapa
    # esquecida volte a consumir memória e derrube a renderização.
    from core.video_processor import low_ram_mode

    if low_ram_mode():
        return Pipeline(
            [
                ApplyEditsStep(),
                ApplyAudioStep(),
                BuildSubtitlesStep(),
                RenderStep(),
                ExportStep(),
            ]
        )

    return Pipeline(
        [
            ApplyEditsStep(),
            ApplyIllustrationsStep(),
            ApplyPackStep(),
            ApplyAudioStep(),
            ApplyLayoutsStep(),
            BuildSubtitlesStep(),
            RenderStep(),
            ExportStep(),
        ]
    )
