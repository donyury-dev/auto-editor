"""Fonte: DALL-E (geração por IA, OpenAI Images API — paga).

Docs: https://platform.openai.com/docs/api-reference/images
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.request
from pathlib import Path

from images.base_provider import ImageProvider, ImageProviderError

logger = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/images/generations"
TIMEOUT_S = 120

# sufixo aplicado ao prompt do usuário (estilo configurável na Settings)
STYLE_SUFFIX = (
    ", ilustração estilizada e moderna, cores vibrantes, estilo conteúdo "
    "viral de redes sociais, composição simples e legível"
)


class DalleProvider(ImageProvider):
    id = "dalle"
    label = "DALL-E (geração por IA)"
    default_model = "dall-e-3"
    env_key = "OPENAI_API_KEY"

    def fetch(self, prompt: str, out_path: Path) -> Path:
        if not self.api_key:
            raise ImageProviderError("API key da OpenAI não configurada.")
        payload = json.dumps(
            {
                "model": self.model or self.default_model,
                "prompt": f"{prompt}{STYLE_SUFFIX}",
                "size": "1024x1024",
                "response_format": "b64_json",
                "n": 1,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise ImageProviderError(f"DALL-E falhou: {exc}") from exc

        items = data.get("data") or []
        if not items or "b64_json" not in items[0]:
            raise ImageProviderError("DALL-E não retornou imagem.")

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(items[0]["b64_json"]))
        return out_path
