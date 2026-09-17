"""Gerenciador de provedores de IA.

Permite trocar o provedor ativo a qualquer momento, sem perder
configurações. As API keys são salvas no cofre do sistema operacional
(keyring); se o keyring não estiver disponível, usa fallback em arquivo
com permissões restritas (chmod 600) e registra um aviso.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Type

from ai.base_provider import AIProvider
from ai.claude_provider import ClaudeProvider
from config.settings import PROVIDERS_CONFIG_PATH

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "auto-editor"


class ProviderNotConfiguredError(RuntimeError):
    """Provedor ativo sem configuração suficiente (ex.: sem API key)."""


class ProviderManager:
    """Registro, configuração e instanciação de provedores de IA."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        use_keyring: bool = True,
    ) -> None:
        self.config_path = Path(config_path or PROVIDERS_CONFIG_PATH)
        self._providers: dict[str, Type[AIProvider]] = {}
        self.register(ClaudeProvider)
        self._keyring_ok = use_keyring and self._keyring_available()
        if not self._keyring_ok:
            logger.warning(
                "Keyring indisponível: API keys serão salvas em "
                "%s com permissões restritas (chmod 600).",
                self.config_path,
            )
        self._config = self._load()

    # ------------------------------------------------------------------
    # Registro de provedores
    # ------------------------------------------------------------------

    def register(self, provider_cls: Type[AIProvider]) -> None:
        """Registra (ou substitui) uma implementação de AIProvider."""
        self._providers[provider_cls.id] = provider_cls

    @property
    def provider_ids(self) -> list[str]:
        return list(self._providers)

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    @staticmethod
    def _keyring_available() -> bool:
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, "__probe__", "x")
            ok = keyring.get_password(KEYRING_SERVICE, "__probe__") == "x"
            keyring.delete_password(KEYRING_SERVICE, "__probe__")
            return bool(ok)
        except Exception as exc:
            logger.debug("Keyring não utilizável: %s", exc)
            return False

    def _load(self) -> dict:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("providers.json inválido (%s); recriando.", exc)
        return {"active": "claude", "providers": {}}

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def describe_providers(self) -> list[dict]:
        """Lista provedores com metadados para exibição na UI."""
        result = []
        for pid, cls in self._providers.items():
            conf = self._config.get("providers", {}).get(pid, {})
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

    def active_id(self) -> str:
        return self._config.get("active", "claude")

    def set_active(self, provider_id: str) -> None:
        if provider_id not in self._providers:
            raise ValueError(f"Provedor desconhecido: {provider_id}")
        self._config["active"] = provider_id
        self._save()
        logger.info("Provedor de IA ativo: %s", provider_id)

    def set_model(self, provider_id: str, model: str) -> None:
        if provider_id not in self._providers:
            raise ValueError(f"Provedor desconhecido: {provider_id}")
        self._config.setdefault("providers", {}).setdefault(provider_id, {})[
            "model"
        ] = model
        self._save()

    def set_api_key(self, provider_id: str, key: str) -> None:
        if not key:
            return
        if self._keyring_ok:
            try:
                import keyring

                keyring.set_password(KEYRING_SERVICE, provider_id, key)
                return
            except Exception as exc:
                logger.warning(
                    "keyring falhou ao salvar (%s); usando fallback em arquivo.",
                    exc,
                )
                self._keyring_ok = False
        self._config.setdefault("providers", {}).setdefault(provider_id, {})[
            "api_key"
        ] = key
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
        key = self._config.get("providers", {}).get(provider_id, {}).get(
            "api_key"
        )
        if key:
            return key
        cls = self._providers.get(provider_id)
        if cls and cls.env_key:
            return os.environ.get(cls.env_key) or None
        return None

    def get_active(self) -> AIProvider:
        """Instancia o provedor ativo com a configuração salva."""
        pid = self.active_id()
        cls = self._providers.get(pid)
        if cls is None:
            raise ProviderNotConfiguredError(
                f"Provedor ativo desconhecido: {pid}"
            )
        api_key = self.get_api_key(pid)
        if cls.requires_api_key and not api_key:
            raise ProviderNotConfiguredError(
                f"Configure a API key do provedor '{cls.label}' em "
                "Configurações > Provedores de IA."
            )
        conf = self._config.get("providers", {}).get(pid, {})
        return cls(api_key=api_key, model=conf.get("model"))
