import os
import importlib
import pytest

from sf.llm import get_provider, LLMRequest, LLMMessage


def test_provider_registry_has_codex_api():
    provider = get_provider("codex_api")
    assert provider.name == "codex_api"


def test_env_override_provider(monkeypatch):
    monkeypatch.setenv("SF_LLM_PROVIDER", "codex_cli")
    provider = get_provider()
    assert provider.name == "codex_cli"


def test_codex_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("SF_LLM_STUB", raising=False)
    with pytest.raises(ValueError):
        get_provider("codex")


def test_codex_stub_enabled(monkeypatch):
    # When SF_LLM_STUB=1, Codex provider should not raise on missing key
    monkeypatch.setenv("SF_LLM_STUB", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    provider = get_provider("codex_api")
    req = LLMRequest(messages=[LLMMessage(role="user", content="hi")])
    result = provider.generate(req)
    assert "files" in result.text or result.text == ""
