"""Modelo de timeline estilo CapCut.

Representa a edição como faixas e clipes editáveis, com adapters para
converter do/para os planos existentes (EditPlan, AudioPlan, ilustrações,
sugestões do pack) sem reescrever o render.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

from core.audio_plan import AudioPlan, SfxEvent
from core.edit_plan import Cut, EditPlan, ZoomEffect
from core.illustration_plan import IllustrationMoment
from core.pack_manager import PackSuggestion


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Clip:
    """Um clipe em uma faixa da timeline."""

    # identidade
    id: str = field(default_factory=_uid)
    kind: str = "video"  # video | image | overlay | callout | music | sfx | transition

    # posição na timeline (segundos)
    start: float = 0.0
    end: float = 0.0

    # referência ao arquivo fonte
    source_path: Path | str | None = None
    source_in: float = 0.0  # offset dentro do arquivo fonte
    source_out: float | None = None  # None = usa duração disponível

    # conteúdo textual (call-outs / legendas)
    text: str = ""

    # propriedades visuais/sonoras ajustáveis
    opacity: float = 1.0
    scale: float = 1.0
    volume: float = 1.0
    x: float = 0.5  # posição horizontal relativa (0..1)
    y: float = 0.5  # posição vertical relativa (0..1)
    animation_in: str = "fade"  # fade | pop | slide_left | slide_up | none
    animation_out: str = "fade"

    # metadados extras (motivo, categoria do pack, LUT, fonte, cor...)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end

    def split_at(self, t: float) -> tuple["Clip", "Clip"]:
        """Divide o clipe em dois no instante t (relativo à timeline)."""
        if not self.start < t < self.end:
            raise ValueError("ponto de corte fora do clipe")
        delta = t - self.start
        left = replace(
            self,
            id=_uid(),
            end=t,
            source_out=self.source_in + delta if self.source_out else None,
        )
        right = replace(
            self,
            id=_uid(),
            start=t,
            source_in=self.source_in + delta,
        )
        return left, right


@dataclass
class Track:
    """Faixa horizontal da timeline."""

    id: str = field(default_factory=_uid)
    name: str = ""
    type: str = "video"  # video | overlay | text | music | sfx
    clips: list[Clip] = field(default_factory=list)
    locked: bool = False
    hidden: bool = False

    def add_clip(self, clip: Clip) -> None:
        self.clips.append(clip)
        self.clips.sort(key=lambda c: c.start)

    def remove_clip(self, clip_id: str) -> bool:
        for i, c in enumerate(self.clips):
            if c.id == clip_id:
                self.clips.pop(i)
                return True
        return False

    def clip_at(self, t: float) -> Clip | None:
        for c in self.clips:
            if c.contains(t):
                return c
        return None

    def clips_in_range(self, t0: float, t1: float) -> list[Clip]:
        return [c for c in self.clips if c.start < t1 and c.end > t0]


@dataclass
class Timeline:
    """Edição completa representada em faixas."""

    id: str = field(default_factory=_uid)
    duration: float = 0.0  # duração do vídeo original/de referência
    tracks: list[Track] = field(default_factory=list)
    playhead: float = 0.0
    zoom: float = 1.0  # >1 aumenta (mostra mais detalhe)
    source_path: Path | str | None = None

    # transição global entre segmentos de vídeo (mesmo domínio de EditPlan)
    transition_type: str = "fade"
    transition_duration: float = 0.3

    def ensure_track(self, type_: str, name: str = "") -> Track:
        for t in self.tracks:
            if t.type == type_:
                return t
        track = Track(name=name or type_, type=type_)
        self.tracks.append(track)
        return track

    def track_by_type(self, type_: str) -> Track | None:
        for t in self.tracks:
            if t.type == type_:
                return t
        return None

    def all_clips(self) -> list[Clip]:
        return [c for t in self.tracks for c in t.clips]

    def move_clip(self, clip_id: str, new_start: float) -> bool:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    delta = new_start - c.start
                    c.start = new_start
                    c.end += delta
                    t.clips.sort(key=lambda x: x.start)
                    return True
        return False

    def resize_clip(self, clip_id: str, new_start: float | None, new_end: float | None) -> bool:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    if new_start is not None:
                        c.start = new_start
                    if new_end is not None:
                        c.end = new_end
                    t.clips.sort(key=lambda x: x.start)
                    return True
        return False


# ---------------------------------------------------------------------------
# Adapters: planos atuais -> Timeline
# ---------------------------------------------------------------------------


class PlanToTimelineAdapter:
    """Converte os planos gerados pela IA em uma timeline inicial editável."""

    def __init__(self, source_video: Path | str, duration: float) -> None:
        self.source_video = Path(source_video)
        self.duration = duration

    def build(
        self,
        edit_plan: EditPlan,
        illustrations: list[IllustrationMoment],
        audio_plan: AudioPlan | None,
        pack_suggestions: list[PackSuggestion],
    ) -> Timeline:
        timeline = Timeline(
            duration=self.duration,
            source_path=self.source_video,
            transition_type=edit_plan.transition_type,
            transition_duration=edit_plan.transition_duration,
        )

        # Faixa principal de vídeo: segmentos mantidos
        video_track = timeline.ensure_track("video", "Vídeo principal")
        for s, e in edit_plan.kept_segments():
            video_track.add_clip(
                Clip(
                    kind="video",
                    start=s,
                    end=e,
                    source_path=self.source_video,
                    source_in=s,
                    source_out=e,
                    meta={"reason": "segmento mantido"},
                )
            )

        # Zooms: guardados como metadado do clipe de vídeo que os contém
        for z in edit_plan.zooms:
            for c in video_track.clips:
                if c.start <= z.start < z.end <= c.end:
                    c.meta.setdefault("zooms", []).append(
                        {
                            "start": z.start,
                            "end": z.end,
                            "intensity": z.intensity,
                            "reason": z.reason,
                        }
                    )

        # Destaques (callout/imagem)
        text_track = timeline.ensure_track("text", "Texto / Destaques")
        overlay_track = timeline.ensure_track("overlay", "Overlays")
        for ill in illustrations:
            if ill.kind == "callout":
                text_track.add_clip(
                    Clip(
                        kind="callout",
                        start=ill.start,
                        end=ill.end,
                        text=ill.callout_text or ill.prompt,
                        meta={"prompt": ill.prompt},
                    )
                )
            elif ill.kind == "image" and ill.image_path:
                overlay_track.add_clip(
                    Clip(
                        kind="image",
                        start=ill.start,
                        end=ill.end,
                        source_path=Path(ill.image_path),
                        meta={"prompt": ill.prompt},
                    )
                )

        # Pack: overlays e LUTs
        for sugg in pack_suggestions:
            if sugg.kind == "overlay" and Path(sugg.path).exists():
                overlay_track.add_clip(
                    Clip(
                        kind="overlay",
                        start=sugg.start,
                        end=sugg.end,
                        source_path=Path(sugg.path),
                        meta={"reason": sugg.reason, "category": sugg.category},
                    )
                )
            elif sugg.kind == "lut":
                # LUT é uma propriedade global/temporal; guardamos num clipe
                # especial na faixa de overlay ou metadado da timeline.
                timeline.transition_type = edit_plan.transition_type

        # Áudio: música + SFX
        if audio_plan:
            if audio_plan.music_path:
                music_track = timeline.ensure_track("music", "Música")
                music_track.add_clip(
                    Clip(
                        kind="music",
                        start=0.0,
                        end=self.duration,
                        source_path=Path(audio_plan.music_path),
                        volume=audio_plan.music_volume,
                        meta={"mood": audio_plan.mood},
                    )
                )
            sfx_track = timeline.ensure_track("sfx", "Efeitos sonoros")
            for ev in audio_plan.sfx:
                path = ev.path or self._resolve_sfx_path(ev.kind)
                sfx_track.add_clip(
                    Clip(
                        kind="sfx",
                        start=ev.timestamp,
                        end=ev.timestamp + 1.5,
                        source_path=Path(path) if path else None,
                        meta={"origin": ev.origin, "kind": ev.kind},
                    )
                )

        return timeline

    @staticmethod
    def _resolve_sfx_path(kind: str) -> Path | None:
        try:
            from audio.sfx_engine import get_sfx

            return Path(get_sfx(kind))
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Adapters: Timeline -> planos atuais
# ---------------------------------------------------------------------------


class TimelineToPlanAdapter:
    """Converte a timeline editada de volta para os planos do render atual."""

    def __init__(self, timeline: Timeline) -> None:
        self.timeline = timeline

    def to_edit_plan(self) -> EditPlan:
        video_track = self.timeline.track_by_type("video")
        if video_track is None:
            return EditPlan(duration=self.timeline.duration)

        # Cortes = gaps entre clipes de vídeo
        cuts: list[Cut] = []
        cursor = 0.0
        for clip in sorted(video_track.clips, key=lambda c: c.start):
            if clip.start > cursor:
                cuts.append(
                    Cut(
                        start=cursor,
                        end=clip.start,
                        reason="removido na timeline",
                    )
                )
            cursor = max(cursor, clip.end)
        if cursor < self.timeline.duration:
            cuts.append(
                Cut(
                    start=cursor,
                    end=self.timeline.duration,
                    reason="removido no final",
                )
            )

        zooms = []
        for clip in video_track.clips:
            for z in clip.meta.get("zooms", []):
                zooms.append(
                    ZoomEffect(
                        start=z["start"],
                        end=z["end"],
                        intensity=z.get("intensity", 0.15),
                        reason=z.get("reason", ""),
                    )
                )

        return EditPlan(
            cuts=cuts,
            zooms=zooms,
            transition_type=self.timeline.transition_type,
            transition_duration=self.timeline.transition_duration,
            duration=self.timeline.duration,
        )

    def to_illustrations(self) -> list[IllustrationMoment]:
        moments: list[IllustrationMoment] = []
        text_track = self.timeline.track_by_type("text")
        if text_track:
            for c in text_track.clips:
                if c.kind == "callout":
                    moments.append(
                        IllustrationMoment(
                            start=c.start,
                            end=c.end,
                            kind="callout",
                            prompt=c.meta.get("prompt", c.text),
                            callout_text=c.text,
                        )
                    )
        overlay_track = self.timeline.track_by_type("overlay")
        if overlay_track:
            for c in overlay_track.clips:
                if c.kind == "image" and c.source_path:
                    moments.append(
                        IllustrationMoment(
                            start=c.start,
                            end=c.end,
                            kind="image",
                            prompt=c.meta.get("prompt", ""),
                            image_path=str(c.source_path),
                        )
                    )
        return moments

    def to_audio_plan(self) -> AudioPlan:
        audio_plan = AudioPlan()
        music_track = self.timeline.track_by_type("music")
        if music_track and music_track.clips:
            first = music_track.clips[0]
            audio_plan.music_path = str(first.source_path) if first.source_path else None
            audio_plan.music_volume = first.volume

        sfx_track = self.timeline.track_by_type("sfx")
        if sfx_track:
            for c in sfx_track.clips:
                audio_plan.sfx.append(
                    SfxEvent(
                        kind=c.meta.get("kind", "whoosh"),
                        timestamp=c.start,
                        path=str(c.source_path) if c.source_path else None,
                        origin=c.meta.get("origin", "timeline"),
                    )
                )
        return audio_plan

    def to_pack_suggestions(self) -> list[PackSuggestion]:
        suggestions: list[PackSuggestion] = []
        overlay_track = self.timeline.track_by_type("overlay")
        if overlay_track:
            for c in overlay_track.clips:
                if c.kind == "overlay" and c.source_path:
                    suggestions.append(
                        PackSuggestion(
                            kind="overlay",
                            path=Path(c.source_path),
                            category=c.meta.get("category", "overlays"),
                            start=c.start,
                            end=c.end,
                            reason=c.meta.get("reason", "adicionado na timeline"),
                        )
                    )
        return suggestions

    def to_lut_path(self) -> Path | None:
        # LUT é raramente um clipe; por ora procura metadado global.
        return self.timeline.meta.get("lut_path")


# monkey-patch leve para Timeline carregar metadados extras
def _timeline_meta(self: Timeline) -> dict[str, Any]:
    if not hasattr(self, "_meta"):
        self._meta = {}
    return self._meta


Timeline.meta = property(_timeline_meta)  # type: ignore[attr-defined]
