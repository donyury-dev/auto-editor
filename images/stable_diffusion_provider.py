"""Fonte: Stable Diffusion (geração por IA, endpoint local ou próprio).

Compatível com a API do Automatic1111 (POST /sdapi/v1/txt2img). A URL
base é configurável em Configurações (campo "model" do provedor).
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.request
from pathlib import Path

from images.base_provider import ImageProvider, ImageProviderError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:7860"
TIMEOUT_S = 180

STYLE_SUFFIX = (
    ", ilustração estilizada e moderna, cores vibrantes, estilo conteúdo "
    "viral de redes sociais, composição simples e legível"
)


class StableDiffusionProvider(ImageProvider):
    id = "stable_diffusion"
    label = "Stable Diffusion (endpoint próprio/local)"
    requires_api_key = False  # A1111 local normalmente não exige key
    default_model = DEFAULT_BASE_URL  # reutilizado como URL base

    def fetch(self, prompt: str, out_path: Path) -> Path:
        base_url = (self.model or DEFAULT_BASE_URL).rstrip("/")
        payload = json.dumps(
            {
                "prompt": f"{prompt}{STYLE_SUFFIX}",
                "width": 1024,
                "height": 1024,
                "steps": 25,
                "cfg_scale": 7,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/sdapi/v1/txt2img",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise ImageProviderError(
                f"Stable Diffusion falhou (endpoint {base_url}): {exc}"
            ) from exc

        images = data.get("images") or []
        if not images:
            raise ImageProviderError("Stable Diffusion não retornou imagem.")

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(images[0]))
        return out_path
