"""Contrato padrão da camada de fontes de imagem (B-roll).

Qualquer fonte (Unsplash, Pexels, DALL-E, Stable Diffusion, placeholder
local...) deve implementar esta interface. O restante do programa depende
apenas deste contrato — trocar de fonte nunca exige reescrever motores.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Optional

logger = logging.getLogger(__name__)


class ImageProviderError(RuntimeError):
    """Falha ao buscar/gerar uma imagem (rede, key inválida, cota...)."""


class ImageProvider(ABC):
    """Interface única para provedores de imagem."""

    id: ClassVar[str] = "base"
    label: ClassVar[str] = "Provedor de imagem base"
    requires_api_key: ClassVar[bool] = True
    env_key: ClassVar[str] = ""  # variável de ambiente usada como fallback
    default_model: ClassVar[str] = ""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.model = model or ""

    @abstractmethod
    def fetch(self, prompt: str, out_path: Path) -> Path:
        """Busca (stock) ou gera (IA) uma imagem para o prompt.

        Deve gravar o arquivo em `out_path` e retorná-lo. Em caso de falha,
        levanta ImageProviderError — o chamador decide o fallback.
        """

    def describe(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "requires_api_key": self.requires_api_key,
        }
