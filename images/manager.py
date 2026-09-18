"""Gerenciador de provedores de imagem (análogo ao ProviderManager de IA).

Permite trocar a fonte de B-roll a qualquer momento. API keys no keyring
(com fallback chmod 600), cache por hash de (provedor + prompt) para não
re-consumir API em re-renderizações.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional, Type

from config.settings import CACHE_DIR, PROVIDERS_CONFIG_PATH
from images.base_provider import ImageProvider, ImageProviderError
from images.dalle_provider import DalleProvider
from images.local_placeholder_provider import LocalPlaceholderProvider
from images.pexels_provider import PexelsProvider
from images.stable_diffusion_provider import StableDiffusionProvider
from images.unsplash_provider import UnsplashProvider

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "auto-editor-images"
IMAGE_CACHE_DIR = CACHE_DIR / "images"


class ImageProviderManager:
    """Registro, configuração, cache e instanciação de fontes de imagem."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        use_keyring: bool = True,
    ) -> None:
        self.config_path = Path(config_path or PROVIDERS_CONFIG_PATH)
        self._providers: dict[str, Type[ImageProvider]] = {}
        for cls in (
            LocalPlaceholderProvider,
            UnsplashProvider,
            PexelsProvider,
            DalleProvider,
            StableDiffusionProvider,
        ):
            self.register(cls)
        self._keyring_ok = use_keyring and self._keyring_available()
        self._config = self._load()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register(self, provider_cls: Type[ImageProvider]) -> None:
        self._providers[provider_cls.id] = provider_cls

    @property
    def provider_ids(self) -> list[str]:
        return list(self._providers)

    # ------------------------------------------------------------------
    # Persistência (mesmo padrão do ProviderManager)
    # ------------------------------------------------------------------

    @staticmethod
    def _keyring_available() -> bool:
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, "__probe__", "x")
            ok = keyring.get_password(KEYRING_SERVICE, "__probe__") == "x"
            keyring.delete_password(KEYRING_SERVICE, "__probe__")
            return bool(ok)
        except Exception:
            return False

    def _load(self) -> dict:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data.get("images", {})
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("providers.json inválido (%s).", exc)
        return {}

    def _save(self) -> None:
        root: dict = {}
        if self.config_path.exists():
            try:
                root = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                root = {}
        root["images"] = self._config
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(root, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def describe_providers(self) -> list[dict]:
        result = []
        for pid, cls in self._providers.items():
            conf = self._config.get(pid, {})
            result.append(
                {
                    "id": pid,
                    "label": cls.label,
                    "model": conf.get("model", cls.default_model),
                    "requires_api_key": cls.requires_api_key,
                    "has_key": bool(self.get_api_key(pid)),
                }
            )
        return result

    def set_model(self, provider_id: str, model: str) -> None:
        if provider_id not in self._providers:
            raise ValueError(f"Provedor desconhecido: {provider_id}")
        self._config.setdefault(provider_id, {})["model"] = model
        self._save()

    def set_api_key(self, provider_id: str, key: str) -> None:
        if not key:
            return
        if self._keyring_ok:
            try:
                import keyring

                keyring.set_password(KEYRING_SERVICE, provider_id, key)
                return
            except Exception:
                self._keyring_ok = False
        self._config.setdefault(provider_id, {})["api_key"] = key
        self._save()

    def get_api_key(self, provider_id: str) -> Optional[str]:
        if self._keyring_ok:
            try:
                import keyring

                key = keyring.get_password(KEYRING_SERVICE, provider_id)
                if key:
                    return key
            except Exception:
                pass
        key = self._config.get(provider_id, {}).get("api_key")
        if key:
            return key
        cls = self._providers.get(provider_id)
        if cls and cls.env_key:
            return os.environ.get(cls.env_key) or None
        return None

    def get(self, provider_id: str) -> ImageProvider:
        """Instancia um provedor específico (levanta se não configurado)."""
        cls = self._providers.get(provider_id)
        if cls is None:
            raise ImageProviderError(f"Provedor de imagem desconhecido: {provider_id}")
        api_key = self.get_api_key(provider_id)
        if cls.requires_api_key and not api_key:
            raise ImageProviderError(
                f"Configure a API key do provedor de imagem '{cls.label}'."
            )
        conf = self._config.get(provider_id, {})
        return cls(api_key=api_key, model=conf.get("model"))

    def get_or_local(self, provider_id: str) -> ImageProvider:
        """Provedor pedido, caindo para o local se não estiver configurado."""
        try:
            return self.get(provider_id)
        except ImageProviderError as exc:
            logger.warning(
                "Provedor de imagem %s indisponível (%s); usando placeholder local.",
                provider_id,
                exc,
            )
            return self.get(LocalPlaceholderProvider.id)

    # ------------------------------------------------------------------
    # Cache por prompt
    # ------------------------------------------------------------------

    def fetch_cached(
        self, provider_id: str, prompt: str, ext: str = "jpg"
    ) -> Path:
        """Busca a imagem com cache: mesmo (provedor, prompt) não refaz.

        Em caso de falha do provedor, cai para o placeholder local —
        a fase de Ilustrações nunca quebra por rede/key.
        """
        digest = hashlib.sha256(
            f"{provider_id}:{prompt}".encode("utf-8")
        ).hexdigest()[:32]
        cached = IMAGE_CACHE_DIR / f"{digest}.{ext}"
        if cached.exists() and cached.stat().st_size > 0:
            logger.debug("Cache de imagem: %s", cached)
            return cached

        provider = self.get_or_local(provider_id)
        IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            return provider.fetch(prompt, cached)
        except ImageProviderError as exc:
            logger.warning(
                "Busca de imagem falhou (%s); gerando placeholder.", exc
            )
            return LocalPlaceholderProvider().fetch(prompt, cached)
