"""Exportação final: move o vídeo renderizado para output/ com nome claro."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from config.settings import OUTPUT_DIR, OutputFormat

logger = logging.getLogger(__name__)


class Exporter:
    """Salva o vídeo final na pasta de saída."""

    def export(
        self,
        rendered_path: Path | str,
        original_stem: str,
        fmt: OutputFormat,
    ) -> Path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"{original_stem}_{fmt.value}_{timestamp}.mp4"
        shutil.move(str(rendered_path), str(output_path))
        logger.info("Vídeo exportado: %s", output_path)
        return output_path
