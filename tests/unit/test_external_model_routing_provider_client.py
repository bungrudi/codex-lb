from __future__ import annotations

from app.core.external_providers.config import ExternalProviderConfig
from app.core.external_providers.openai_compatible import OpenAICompatibleProviderClient


def test_provider_client_uses_provider_auth_and_sanitizes_client_headers() -> None:
    provider = ExternalProviderConfig(
        id="openrouter",
        kind="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_headers={"HTTP-Referer": "https://codex-lb.local"},
    )
    client = OpenAICompatibleProviderClient(provider, api_key="sk-provider")

    headers = client._headers(
        {
            "Authorization": "Bearer sk-client",
            "ChatGPT-Account-ID": "acc_123",
            "X-Api-Key": "sk-client",
            "X-Codex-Bridge-Token": "bridge-secret",
            "Connection": "keep-alive",
            "X-Request-ID": "req_123",
        },
        accept="application/json",
    )

    assert headers["Authorization"] == "Bearer sk-provider"
    assert headers["HTTP-Referer"] == "https://codex-lb.local"
    assert headers["X-Request-ID"] == "req_123"
    assert "ChatGPT-Account-ID" not in headers
    assert "X-Api-Key" not in headers
    assert "X-Codex-Bridge-Token" not in headers
    assert "Connection" not in headers
