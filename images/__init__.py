"""Camada de fontes de imagem (B-roll) — plugável, como ai/."""

from images.base_provider import ImageProvider, ImageProviderError
from images.manager import ImageProviderManager

__all__ = ["ImageProvider", "ImageProviderError", "ImageProviderManager"]
