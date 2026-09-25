"""Mixer de áudio (Fase 4): normalização da voz + música com ducking + SFX.

Ordem de processamento (importante — exigência do projeto):
1. A VOZ é normalizada primeiro (loudnorm EBU R128, alvo -16 LUFS, padrão
   de redes sociais). Sem isso, uma voz baixa (ex.: -34dB) sumiria atrás
   da música mesmo com ducking.
2. A música passa pelo sidechaincompress comandado PELA VOZ já
   normalizada — quando há fala, a trilha abaixa automaticamente.
3. Os efeitos sonoros (whoosh/ding/impacto/pop) entram nos timestamps
   aprovados na revisão.

O vídeo é copiado sem re-encode (-c:v copy): só o áudio é recodificado.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable, Optional

from audio.sfx_engine import get_sfx
from core.audio_plan import AudioPlan, SfxEvent
from core.ffmpeg_path import get_ffmpeg
from core.video_processor import VideoInfo, VideoProcessingError, VideoProcessor

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]

VOICE_TARGET_LUFS = -16.0  # padrão de loudness para Reels/TikTok/Shorts
VOICE_TRUE_PEAK = -1.5
SFX_VOLUME = 0.5  # volume linear dos efeitos na mixagem


def build_audio_filter(
    plan: AudioPlan,
    sfx_events: list[SfxEvent],
    sfx_input_count: int,
    has_voice: bool,
    duration: float = 0.0,
) -> str:
    """Monta o filter_complex de áudio (função pura, testável).

    `sfx_input_count` é o número de entradas de SFX JÁ adicionadas ao
    comando (índices dos inputs começam depois do vídeo e da música).
    """
    parts: list[str] = []
    music_idx = 1 if plan.music_path else None

    if not has_voice:
        # vídeo sem faixa de voz: silêncio como base da mixagem
        trim = f",atrim=duration={duration:.3f}" if duration else ""
        parts.append(f"anullsrc=r=48000:cl=stereo{trim}[voice]")
    elif plan.normalize_voice:
        parts.append(
            f"[0:a]loudnorm=I={VOICE_TARGET_LUFS}:TP={VOICE_TRUE_PEAK}"
            f":LRA=11,aresample=48000,"
            f"aformat=sample_rates=48000:channel_layouts=stereo[voice]"
        )
    else:
        # sem normalização, mas com formato uniforme p/ o amix
        parts.append(
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice]"
        )
    voice_src = "[voice]"

    mix_inputs: list[str] = []

    if plan.music_path:
        parts.append(
            f"{voice_src}asplit=2[vmix][vside]"
        )
        parts.append(
            f"[{music_idx}:a]aformat=sample_rates=48000"
            f":channel_layouts=stereo,volume={plan.music_volume:.3f}[m_pre]"
        )
        # ducking: a voz (normalizada) comanda a compressão da música
        parts.append(
            "[m_pre][vside]sidechaincompress=threshold=0.03:ratio=8"
            ":attack=25:release=450[music]"
        )
        mix_inputs.append("[vmix]")
        mix_inputs.append("[music]")
    else:
        mix_inputs.append(voice_src)

    for i, event in enumerate(sfx_events):
        idx = (2 if music_idx is not None else 1) + i
        delay_ms = int(max(0.0, event.timestamp) * 1000)
        parts.append(
            f"[{idx}:a]aformat=sample_rates=48000"
            f":channel_layouts=stereo,adelay={delay_ms}:all=1,"
            f"volume={SFX_VOLUME:.3f}[sfx{i}]"
        )
        mix_inputs.append(f"[sfx{i}]")

    # normalize=0 preserva os níveis; alimiter evita clipping da soma
    parts.append(
        f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}"
        f":duration=first:normalize=0,"
        f"alimiter=level_in=1:limit=0.95[aout]"
    )
    assert sfx_input_count == len(sfx_events)
    return ";".join(parts)


class AudioMixer:
    """Aplica o plano de áudio aprovado ao vídeo editado."""

    def __init__(self, sfx_cache_dir: Optional[Path] = None) -> None:
        self._sfx_cache_dir = sfx_cache_dir

    def apply(
        self,
        video_path: Path | str,
        plan: AudioPlan,
        info: VideoInfo,
        output_path: Path | str,
        progress: Optional[ProgressFn] = None,
    ) -> Path:
        video_path = Path(video_path)
        output_path = Path(output_path)

        has_music = plan.music_path is not None and Path(plan.music_path).exists()
        if has_music:
            logger.info("Trilha selecionada: %s", plan.music_path)
        else:
            if plan.music_path:
                logger.warning(
                    "Trilha não encontrada (%s); seguindo sem música.",
                    plan.music_path,
                )
            plan.music_path = None

        events = list(plan.sfx)
        nothing_to_do = (
            not has_music and not events and not plan.normalize_voice
        )
        if nothing_to_do or not (info.has_audio or has_music or events):
            logger.info("Nada a mixar; copiando o vídeo.")
            if video_path != output_path:
                shutil.copyfile(video_path, output_path)
            if progress:
                progress(1.0, "áudio inalterado")
            return output_path

        # efeitos: sintetiza (ou pega do cache) um WAV por tipo
        sfx_by_kind: dict[str, Path] = {}
        for event in events:
            if event.kind not in sfx_by_kind:
                sfx_by_kind[event.kind] = get_sfx(
                    event.kind, self._sfx_cache_dir
                )

        cmd = [get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path)]
        if plan.music_path:
            # trilha em loop (cobre vídeos maiores que a música)
            cmd += ["-stream_loop", "-1", "-i", str(plan.music_path)]
        for event in events:
            cmd += ["-i", str(sfx_by_kind[event.kind])]

        fc = build_audio_filter(
            plan,
            events,
            len(events),
            has_voice=info.has_audio,
            duration=info.duration if not info.has_audio else 0.0,
        )
        cmd += [
            "-filter_complex", fc,
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        VideoProcessor()._run_ffmpeg(cmd, "mixagem de áudio")
        if progress:
            progress(
                1.0,
                "áudio mixado"
                + (" com trilha e ducking" if has_music else "")
                + (f" + {len(events)} efeito(s)" if events else ""),
            )
        logger.info("Áudio mixado: %s", output_path)
        return output_path
