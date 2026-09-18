"""Testes dos provedores de imagem (images/)."""

import json

import pytest

from images.base_provider import ImageProvider, ImageProviderError
from images.local_placeholder_provider import LocalPlaceholderProvider
from images.manager import ImageProviderManager


def test_local_placeholder_gera_arquivo(tmp_path):
    provider = LocalPlaceholderProvider()
    out = tmp_path / "card.jpg"
    result = provider.fetch("casa na praia", out)
    assert result == out
    assert out.stat().st_size > 0


def test_local_placeholder_deterministico(tmp_path):
    provider = LocalPlaceholderProvider()
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    provider.fetch("mesmo prompt", a)
    provider.fetch("mesmo prompt", b)
    assert a.read_bytes() == b.read_bytes()


def test_manager_registra_todos_os_provedores(tmp_path):
    manager = ImageProviderManager(config_path=tmp_path / "providers.json")
    ids = manager.provider_ids
    assert "local" in ids
    assert "unsplash" in ids
    assert "pexels" in ids
    assert "dalle" in ids
    assert "stable_diffusion" in ids


def test_manager_get_sem_key_levanta(tmp_path):
    manager = ImageProviderManager(config_path=tmp_path / "providers.json")
    with pytest.raises(ImageProviderError):
        manager.get("unsplash")


def test_manager_get_or_local_cai_para_local(tmp_path):
    manager = ImageProviderManager(config_path=tmp_path / "providers.json")
    provider = manager.get_or_local("unsplash")  # sem key configurada
    assert isinstance(provider, LocalPlaceholderProvider)


def test_manager_fetch_cached_usa_cache(tmp_path, monkeypatch):
    import images.manager as manager_mod

    # isola o cache desta execução (não usar cache/ global do projeto)
    monkeypatch.setattr(
        manager_mod, "IMAGE_CACHE_DIR", tmp_path / "imgcache"
    )
    manager = ImageProviderManager(
        config_path=tmp_path / "providers.json", use_keyring=False
    )
    calls = []

    def fake_fetch(self, prompt, out_path):
        calls.append(prompt)
        out_path.write_bytes(b"img")
        return out_path

    monkeypatch.setattr(LocalPlaceholderProvider, "fetch", fake_fetch)

    a = manager.fetch_cached("local", "casa na praia")
    b = manager.fetch_cached("local", "casa na praia")
    assert a == b
    assert len(calls) == 1  # segunda chamada servida pelo cache


def test_manager_fetch_cached_fallback_quando_provedor_falha(
    tmp_path, monkeypatch
):
    manager = ImageProviderManager(
        config_path=tmp_path / "providers.json", use_keyring=False
    )

    class BrokenProvider(ImageProvider):
        id = "broken"
        label = "Quebrado"
        requires_api_key = False

        def fetch(self, prompt, out_path):
            raise ImageProviderError("sem rede")

    manager.register(BrokenProvider)
    path = manager.fetch_cached("broken", "casa na praia")
    assert path.exists()  # placeholder local gerado como fallback


def test_unsplash_provedor_sem_key_leva_erro(tmp_path):
    from images.unsplash_provider import UnsplashProvider

    provider = UnsplashProvider()
    with pytest.raises(ImageProviderError):
        provider.fetch("praia", tmp_path / "x.jpg")


def test_pexels_provedor_sem_key_leva_erro(tmp_path):
    from images.pexels_provider import PexelsProvider

    provider = PexelsProvider()
    with pytest.raises(ImageProviderError):
        provider.fetch("praia", tmp_path / "x.jpg")


def test_config_compartilhada_com_providers_de_ia(tmp_path):
    """providers.json guarda as duas seções sem conflito."""
    path = tmp_path / "providers.json"
    img_manager = ImageProviderManager(config_path=path, use_keyring=False)
    img_manager.set_api_key("unsplash", "key-123")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["images"]["unsplash"]["api_key"] == "key-123"

    # um segundo manager lê a mesma seção
    other = ImageProviderManager(config_path=path, use_keyring=False)
    assert other.get_api_key("unsplash") == "key-123"
