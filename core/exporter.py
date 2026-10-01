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
        output_dir: Path | str | None = None,
    ) -> Path:
        # Pasta escolhida pelo usuário nas Configurações; se vazia ou
        # indisponível, cai para a pasta padrão do app (%APPDATA%).
        target_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Pasta de saída %s indisponível (%s); usando %s",
                target_dir, exc, OUTPUT_DIR,
            )
            target_dir = OUTPUT_DIR
            target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = target_dir / f"{original_stem}_{fmt.value}_{timestamp}.mp4"
        shutil.move(str(rendered_path), str(output_path))
        logger.info("Vídeo exportado: %s", output_path)
        return output_path
