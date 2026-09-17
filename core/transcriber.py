"""Motor de transcrição: áudio/vídeo -> texto com timestamps por palavra.

Usa faster-whisper (Whisper local, gratuito). Detecta automaticamente GPU
CUDA e cai para CPU quando não há GPU disponível.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from core.models import Transcript, Word

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


class TranscriptionEngine:
    """Wrapper do faster-whisper com auto-detecção de dispositivo."""

    def __init__(
        self,
        model_size: str = "small",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> None:
        self.model_size = model_size
        self.device = device or self.detect_device()
        self.compute_type = compute_type or (
            "float16" if self.device == "cuda" else "int8"
        )

    @staticmethod
    def detect_device() -> str:
        """Retorna 'cuda' se houver GPU utilizável, senão 'cpu'."""
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda"
        except Exception as exc:
            logger.debug("Detecção de CUDA indisponível: %s", exc)
        return "cpu"

    def transcribe(
        self, media_path: Path | str, progress: Optional[ProgressFn] = None
    ) -> Transcript:
        """Transcreve o arquivo de mídia e retorna Transcript palavra a palavra."""
        from faster_whisper import WhisperModel

        media_path = Path(media_path)
        if progress:
            progress(
                0.0,
                f"carregando modelo Whisper '{self.model_size}' "
                f"({self.device})…",
            )
        logger.info(
            "Transcrevendo %s (modelo=%s, device=%s)",
            media_path.name,
            self.model_size,
            self.device,
        )
        model = WhisperModel(
            self.model_size, device=self.device, compute_type=self.compute_type
        )
        segments, info = model.transcribe(
            str(media_path), word_timestamps=True, vad_filter=True
        )

        words: list[Word] = []
        total = float(info.duration or 0.0)
        for segment in segments:
            for w in segment.words or []:
                text = w.word.strip()
                if text:
                    words.append(Word(text=text, start=w.start, end=w.end))
            if progress and total > 0:
                progress(
                    min(segment.end / total, 1.0),
                    f"transcrevendo… {segment.end:.0f}s de {total:.0f}s",
                )

        if progress:
            progress(1.0, "transcrição concluída")
        logger.info(
            "Transcrição concluída: %d palavras (idioma=%s)",
            len(words),
            info.language,
        )
        return Transcript(words=words, language=info.language, duration=total)
