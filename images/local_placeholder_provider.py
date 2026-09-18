"""Provedor local de placeholder — sem API key, sem rede.

Gera uma "cartela" estilizada (gradiente + palavra-chave) para o B-roll.
É o provedor padrão: garante que a fase de Ilustrações funcione em
qualquer máquina, sem custo nem cadastro. As cores derivam do hash do
prompt, então o mesmo prompt sempre gera a mesma arte (determinístico).
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from pathlib import Path

import cv2
import numpy as np

from images.base_provider import ImageProvider

logger = logging.getLogger(__name__)

SIZE = 1024
MAX_LINES = 6
CHARS_PER_LINE = 16


def _strip_accents(text: str) -> str:
    # fontes Hershey do OpenCV são ASCII-only
    return (
        unicodedata.normalize("NFD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
        if len(lines) >= MAX_LINES:
            break
    if current and len(lines) < MAX_LINES:
        lines.append(current)
    return lines or [text[:width]]


class LocalPlaceholderProvider(ImageProvider):
    id = "local"
    label = "Placeholder local (sem API, sem custo)"
    requires_api_key = False

    def fetch(self, prompt: str, out_path: Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # paleta determinística a partir do prompt
        digest = hashlib.sha256(prompt.encode("utf-8")).digest()
        hue_top = int(digest[0]) / 255.0 * 180
        hue_bottom = (hue_top + 40) % 180

        top = np.full((1, 1, 3), (hue_top, 170, 90), dtype=np.uint8)
        bottom = np.full((1, 1, 3), (hue_bottom, 200, 55), dtype=np.uint8)
        top_bgr = cv2.cvtColor(top, cv2.COLOR_HSV2BGR)[0, 0]
        bottom_bgr = cv2.cvtColor(bottom, cv2.COLOR_HSV2BGR)[0, 0]

        # gradiente vertical
        t = np.linspace(0, 1, SIZE, dtype=np.float32)
        grad = (1 - t)[:, None]  # (SIZE, 1)
        img = (
            bottom_bgr[None, None, :] * (1 - grad[..., None])
            + top_bgr[None, None, :] * grad[..., None]
        ).astype(np.uint8)
        img = np.repeat(img, SIZE, axis=1)

        # moldura
        cv2.rectangle(img, (24, 24), (SIZE - 24, SIZE - 24), (255, 255, 255), 4)

        # texto centralizado
        text = _strip_accents(prompt.upper().strip())
        lines = _wrap(text, CHARS_PER_LINE)
        font = cv2.FONT_HERSHEY_DUPLEX
        font_scale = 2.2 if max(len(l) for l in lines) <= 10 else 1.6
        thickness = 6
        line_h = int(60 * font_scale / 1.6) + 30
        total_h = line_h * len(lines)
        y0 = (SIZE - total_h) // 2 + line_h // 2
        for i, line in enumerate(lines):
            (tw, _), _ = cv2.getTextSize(
                line, font, font_scale, thickness
            )
            x = (SIZE - tw) // 2
            y = y0 + i * line_h
            cv2.putText(
                img, line, (x, y), font, font_scale, (0, 0, 0), thickness + 4,
                cv2.LINE_AA,
            )
            cv2.putText(
                img, line, (x, y), font, font_scale, (255, 255, 255), thickness,
                cv2.LINE_AA,
            )

        if not cv2.imwrite(str(out_path), img):
            raise RuntimeError(f"Falha ao gravar placeholder em {out_path}")
        logger.debug("Placeholder gerado para %r em %s", prompt, out_path)
        return out_path
