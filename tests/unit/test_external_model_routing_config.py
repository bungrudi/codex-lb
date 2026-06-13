from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.core.config.settings import Settings
from app.core.external_providers.config import (
    parse_external_model_route_configs,
    parse_external_provider_configs,
)


def test_external_provider_and_route_json_settings_parse() -> None:
    settings = Settings.model_validate(
        {
            "external_providers_json": json.dumps(
                {
                    "openrouter": {
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key_env": "OPENROUTER_API_KEY",
                        "default_headers": {"HTTP-Referer": "https://codex-lb.local"},
                        "timeout_seconds": 120,
                    }
                }
            ),
            "external_model_routes_json": json.dumps(
                {
                    "gpt-5.3-codex": {
                        "provider_id": "openrouter",
                        "target_model": "minimax/minimax-m3",
                        "endpoints": ["chat.completions", "responses"],
                        "strip_request_fields": ["service_tier"],
                    }
                }
            ),
        }
    )

    provider = settings.external_providers_json["openrouter"]
    route = settings.external_model_routes_json["gpt-5.3-codex"]

    assert provider.base_url == "https://openrouter.ai/api/v1"
    assert provider.api_key_env == "OPENROUTER_API_KEY"
    assert provider.default_headers == {"HTTP-Referer": "https://codex-lb.local"}
    assert provider.timeout_seconds == 120
    assert route.public_model == "gpt-5.3-codex"
    assert route.provider_id == "openrouter"
    assert route.target_model == "minimax/minimax-m3"
    assert route.endpoints == frozenset({"chat.completions", "responses"})
    assert route.strip_request_fields == frozenset({"service_tier"})


def test_external_route_requires_known_provider() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate(
            {
                "external_providers_json": json.dumps({}),
                "external_model_routes_json": json.dumps(
                    {"gpt-5.3-codex": {"provider_id": "missing", "target_model": "minimax/minimax-m3"}}
                ),
            }
        )

    assert "references unknown provider" in str(exc_info.value)


def test_external_provider_rejects_insecure_base_url_by_default() -> None:
    with pytest.raises(ValueError, match="must use https"):
        parse_external_provider_configs(
            {"openrouter": {"base_url": "http://openrouter.invalid/api/v1", "api_key_env": "OPENROUTER_API_KEY"}}
        )


def test_external_provider_rejects_invalid_api_key_env_name() -> None:
    with pytest.raises(ValueError, match="api_key_env"):
        parse_external_provider_configs(
            {"openrouter": {"base_url": "https://openrouter.invalid/api/v1", "api_key_env": "not-valid"}}
        )


def test_external_route_defaults_to_chat_completions_only() -> None:
    routes = parse_external_model_route_configs(
        {"gpt-5.3-codex": {"provider_id": "openrouter", "target_model": "minimax/minimax-m3"}}
    )

    assert routes["gpt-5.3-codex"].endpoints == frozenset({"chat.completions"})


def test_external_route_rejects_unimplemented_fallback() -> None:
    with pytest.raises(ValueError, match="fallback_to_codex_pool"):
        parse_external_model_route_configs(
            {
                "gpt-5.3-codex": {
                    "provider_id": "openrouter",
                    "target_model": "minimax/minimax-m3",
                    "fallback_to_codex_pool": True,
                }
            }
        )
