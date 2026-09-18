"""Fonte: Pexels (busca em banco stock, API gratuita com cadastro).

Docs: https://www.pexels.com/api/ — licença comercial permitida.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path

from images.base_provider import ImageProvider, ImageProviderError

logger = logging.getLogger(__name__)

API_SEARCH = "https://api.pexels.com/v1/search"
TIMEOUT_S = 20


class PexelsProvider(ImageProvider):
    id = "pexels"
    label = "Pexels (banco stock gratuito)"
    env_key = "PEXELS_API_KEY"

    def fetch(self, prompt: str, out_path: Path) -> Path:
        if not self.api_key:
            raise ImageProviderError("API key do Pexels não configurada.")
        query = urllib.parse.quote(prompt)
        url = f"{API_SEARCH}?query={query}&per_page=1&orientation=portrait"
        request = urllib.request.Request(
            url, headers={"Authorization": self.api_key}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise ImageProviderError(f"Pexels falhou: {exc}") from exc

        photos = data.get("photos") or []
        if not photos:
            raise ImageProviderError(
                f"Nenhuma foto encontrada no Pexels para: {prompt!r}"
            )
        image_url = (
            photos[0].get("src", {}).get("large2x")
            or photos[0]["src"]["original"]
        )

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        dl = urllib.request.Request(image_url)
        try:
            with urllib.request.urlopen(dl, timeout=TIMEOUT_S) as resp:
                out_path.write_bytes(resp.read())
        except Exception as exc:
            raise ImageProviderError(f"Download Pexels falhou: {exc}") from exc
        return out_path
