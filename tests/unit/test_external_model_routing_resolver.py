from __future__ import annotations

from app.core.config.settings import Settings
from app.core.external_providers.resolver import ExternalRouteResolutionStatus, resolve_external_model_route


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "external_providers_json": {
                "openrouter": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                }
            },
            "external_model_routes_json": {
                "gpt-5.3-codex": {
                    "provider_id": "openrouter",
                    "target_model": "minimax/minimax-m3",
                    "endpoints": ["chat.completions"],
                }
            },
        }
    )


def test_resolver_returns_no_route_without_exact_public_model_match() -> None:
    result = resolve_external_model_route("gpt-5.3", "chat.completions", settings=_settings())

    assert result.status == ExternalRouteResolutionStatus.NO_ROUTE
    assert result.route is None


def test_resolver_rejects_unsupported_endpoint_before_provider_lookup() -> None:
    result = resolve_external_model_route(
        "gpt-5.3-codex",
        "responses",
        settings=_settings(),
        environ={"OPENROUTER_API_KEY": "sk-or-test"},
    )

    assert result.status == ExternalRouteResolutionStatus.ENDPOINT_UNSUPPORTED
    assert result.route is not None
    assert result.provider is None
    assert "does not support endpoint" in (result.reason or "")


def test_resolver_requires_provider_api_key_env() -> None:
    result = resolve_external_model_route("gpt-5.3-codex", "chat.completions", settings=_settings(), environ={})

    assert result.status == ExternalRouteResolutionStatus.PROVIDER_UNAVAILABLE
    assert result.provider is not None
    assert "OPENROUTER_API_KEY" in (result.reason or "")


def test_resolver_rejects_disabled_provider() -> None:
    settings = Settings.model_validate(
        {
            "external_providers_json": {
                "openrouter": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "enabled": False,
                }
            },
            "external_model_routes_json": {
                "gpt-5.3-codex": {
                    "provider_id": "openrouter",
                    "target_model": "minimax/minimax-m3",
                    "endpoints": ["chat.completions"],
                }
            },
        }
    )

    result = resolve_external_model_route(
        "gpt-5.3-codex",
        "chat.completions",
        settings=settings,
        environ={"OPENROUTER_API_KEY": "sk-or-test"},
    )

    assert result.status == ExternalRouteResolutionStatus.PROVIDER_UNAVAILABLE


def test_resolver_matches_enabled_provider_and_route() -> None:
    result = resolve_external_model_route(
        "gpt-5.3-codex",
        "chat.completions",
        settings=_settings(),
        environ={"OPENROUTER_API_KEY": "sk-or-test"},
    )

    assert result.status == ExternalRouteResolutionStatus.MATCH
    assert result.matched
    assert result.route is not None
    assert result.provider is not None
    assert result.route.public_model == "gpt-5.3-codex"
    assert result.route.target_model == "minimax/minimax-m3"
    assert result.provider.id == "openrouter"
