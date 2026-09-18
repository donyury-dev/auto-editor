"""Fonte: Unsplash (busca em banco stock, API gratuita com cadastro).

Docs: https://unsplash.com/developers — licença comercial permitida.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path

from images.base_provider import ImageProvider, ImageProviderError

logger = logging.getLogger(__name__)

API_SEARCH = "https://api.unsplash.com/search/photos"
TIMEOUT_S = 20


class UnsplashProvider(ImageProvider):
    id = "unsplash"
    label = "Unsplash (banco stock gratuito)"
    env_key = "UNSPLASH_ACCESS_KEY"

    def fetch(self, prompt: str, out_path: Path) -> Path:
        if not self.api_key:
            raise ImageProviderError(
                "Access key do Unsplash não configurada."
            )
        query = urllib.parse.quote(prompt)
        url = (
            f"{API_SEARCH}?query={query}&per_page=1&orientation=portrait"
            f"&client_id={self.api_key}"
        )
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise ImageProviderError(f"Unsplash falhou: {exc}") from exc

        results = data.get("results") or []
        if not results:
            raise ImageProviderError(
                f"Nenhuma foto encontrada no Unsplash para: {prompt!r}"
            )
        image_url = results[0]["urls"].get("regular") or results[0]["urls"]["raw"]
        return self._download(image_url, out_path)

    @staticmethod
    def _download(url: str, out_path: Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
                out_path.write_bytes(resp.read())
        except Exception as exc:
            raise ImageProviderError(
                f"Download Unsplash falhou: {exc}"
            ) from exc
        return out_path
