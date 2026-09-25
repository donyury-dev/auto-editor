"""Testes dos provedores OpenAI e Ollama (APIs mockadas)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai.ollama_provider import OllamaProvider
from ai.openai_provider import OpenAIProvider


class _FakeChoice:
    def __init__(self, content: str):
        self.message = MagicMock(content=content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


def test_openai_analyze_transcript():
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
    fake_response = _FakeResponse(
        '{"summary": "resumo", "tone": "animado", "keywords": ["a", "b"]}'
    )
    with patch.object(provider, "_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = (
            fake_response
        )
        result = provider.analyze_transcript("olá mundo")

    assert result.summary == "resumo"
    assert result.tone == "animado"
    assert result.keywords == ["a", "b"]


def test_openai_suggest_edit_plan():
    provider = OpenAIProvider(api_key="sk-test")
    fake_response = _FakeResponse(
        '{"cuts": [{"start": 1.0, "end": 2.0, "reason": "silêncio"}], '
        '"zooms": [{"start": 3.0, "end": 4.0, "intensity": 0.15, '
        '"reason": "ênfase"}], "transition_type": "corte", '
        '"transition_duration": 0.1}'
    )
    with patch.object(provider, "_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = (
            fake_response
        )
        plan = provider.suggest_edit_plan(
            "olá", [{"start": 0.0, "end": 0.5, "text": "olá"}], 5.0
        )

    assert len(plan["cuts"]) == 1
    assert plan["transition_type"] == "corte"
    assert plan["zooms"][0]["intensity"] == 0.15


def test_openai_suggest_illustration_moments():
    provider = OpenAIProvider(api_key="sk-test")
    fake_response = _FakeResponse(
        '{"moments": [{"start": 0.5, "end": 2.0, "text": "casa", '
        '"prompt": "casa grande", "kind": "callout", '
        '"callout_text": "CASA"}]}'
    )
    with patch.object(provider, "_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value = (
            fake_response
        )
        moments = provider.suggest_illustration_moments(
            "imagina uma casa", [{"start": 0.0, "end": 0.5, "text": "casa"}], 3.0
        )

    assert len(moments) == 1
    assert moments[0]["kind"] == "callout"
    assert moments[0]["callout_text"] == "CASA"


def test_ollama_analyze_transcript():
    provider = OllamaProvider(model="llama3.2")
    fake_response = MagicMock(
        json=lambda: {
            "message": {
                "content": '{"summary": "resumo", "tone": "calmo", '
                           '"keywords": ["x"]}'
            }
        },
        raise_for_status=lambda: None,
    )
    with patch("requests.post", return_value=fake_response):
        result = provider.analyze_transcript("olá mundo")

    assert result.summary == "resumo"
    assert result.tone == "calmo"
    assert result.keywords == ["x"]


def test_ollama_conexao_falha_levanta_erro_amigavel():
    provider = OllamaProvider(model="llama3.2", base_url="http://ollama:11434")
    import requests

    with patch(
        "requests.post",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            provider.analyze_transcript("olá")

    assert "Não foi possível conectar ao Ollama" in str(exc_info.value)
    assert "http://ollama:11434" in str(exc_info.value)
