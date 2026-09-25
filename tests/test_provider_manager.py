import pytest

from ai.base_provider import AIProvider
from ai.models import Callout, Highlight, MusicMood, TranscriptAnalysis
from ai.provider_manager import (
    ProviderManager,
    ProviderNotConfiguredError,
)


class FakeProvider(AIProvider):
    id = "fake"
    label = "Fake Provider"
    default_model = "fake-1"
    requires_api_key = True
    supports_base_url = True
    env_key = "FAKE_API_KEY"

    def __init__(self, api_key=None, model=None, base_url=None):
        super().__init__(api_key=api_key, model=model, base_url=base_url)

    def analyze_transcript(self, transcript_text, language="pt"):
        return TranscriptAnalysis()

    def suggest_highlights(self, transcript_text, segments=None, max_highlights=5):
        return []

    def generate_caption_text(self, transcript_text, max_callouts=5):
        return []

    def suggest_music_mood(self, transcript_text):
        return MusicMood()

    def suggest_edit_plan(self, transcript_text, segments, duration, language="pt"):
        return {"cuts": [], "zooms": [], "transition_type": "fade",
                "transition_duration": 0.3}


def make_manager(tmp_path) -> ProviderManager:
    manager = ProviderManager(
        config_path=tmp_path / "providers.json", use_keyring=False
    )
    manager.register(FakeProvider)
    return manager


def test_registra_e_descreve_provedores(tmp_path):
    manager = make_manager(tmp_path)
    described = {p["id"]: p for p in manager.describe_providers()}
    assert "claude" in described
    assert "openai" in described
    assert "ollama" in described
    assert "fake" in described
    assert described["fake"]["model"] == "fake-1"
    assert described["fake"]["supports_base_url"] is True


def test_base_url_eh_persistido_e_passado_ao_provider(tmp_path):
    manager = make_manager(tmp_path)
    manager.set_api_key("fake", "key-fake")
    manager.set_model("fake", "fake-2")
    manager.set_base_url("fake", "http://localhost:9999")
    manager.set_active("fake")

    provider = manager.get_active()
    assert provider.base_url == "http://localhost:9999"

    # recarrega do disco
    manager2 = ProviderManager(
        config_path=manager.config_path, use_keyring=False
    )
    manager2.register(FakeProvider)
    manager2.set_active("fake")
    provider2 = manager2.get_active()
    assert provider2.base_url == "http://localhost:9999"
    assert provider2.model == "fake-2"


def test_provedor_ativo_sem_key_dispara_erro(tmp_path):
    manager = make_manager(tmp_path)
    manager.set_active("fake")
    with pytest.raises(ProviderNotConfiguredError):
        manager.get_active()


def test_api_key_fallback_em_arquivo_e_instanciacao(tmp_path, monkeypatch):
    monkeypatch.delenv("FAKE_API_KEY", raising=False)
    manager = make_manager(tmp_path)
    manager.set_active("fake")
    manager.set_api_key("fake", "abc123")

    assert manager.get_api_key("fake") == "abc123"
    provider = manager.get_active()
    assert isinstance(provider, FakeProvider)
    assert provider.api_key == "abc123"
    assert provider.model == "fake-1"


def test_troca_de_provedor_mantem_configuracoes(tmp_path):
    manager = make_manager(tmp_path)
    manager.set_api_key("fake", "key-fake")
    manager.set_model("fake", "fake-2")
    manager.set_active("fake")

    # troca para claude e volta: configurações do fake continuam salvas
    manager.set_active("claude")
    manager.set_active("fake")

    provider = manager.get_active()
    assert provider.model == "fake-2"
    assert provider.api_key == "key-fake"


def test_env_var_como_fallback_de_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "via-env")
    manager = make_manager(tmp_path)
    manager.set_active("fake")
    assert manager.get_api_key("fake") == "via-env"