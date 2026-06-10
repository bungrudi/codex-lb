from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from app.core.config.settings import Settings, get_settings
from app.core.external_providers.config import ExternalModelRouteConfig, ExternalProviderConfig, ExternalRouteEndpoint
from app.core.external_providers.runtime_config import get_external_routing_config_cache


class ExternalRouteResolutionStatus(StrEnum):
    NO_ROUTE = "no_route"
    MATCH = "match"
    ENDPOINT_UNSUPPORTED = "endpoint_unsupported"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


@dataclass(frozen=True, slots=True)
class ExternalRouteResolution:
    status: ExternalRouteResolutionStatus
    route: ExternalModelRouteConfig | None = None
    provider: ExternalProviderConfig | None = None
    reason: str | None = None

    @property
    def matched(self) -> bool:
        return (
            self.status == ExternalRouteResolutionStatus.MATCH and self.route is not None and self.provider is not None
        )


def resolve_external_model_route(
    public_model: str | None,
    endpoint: ExternalRouteEndpoint,
    *,
    settings: Settings | None = None,
    environ: dict[str, str] | None = None,
) -> ExternalRouteResolution:
    effective_settings = settings or get_settings()
    return _resolve_external_model_route_from_config(
        public_model,
        endpoint,
        providers=effective_settings.external_providers_json,
        routes=effective_settings.external_model_routes_json,
        environ=environ,
    )


async def resolve_external_model_route_async(
    public_model: str | None,
    endpoint: ExternalRouteEndpoint,
    *,
    environ: dict[str, str] | None = None,
) -> ExternalRouteResolution:
    config = await get_external_routing_config_cache().get()
    return _resolve_external_model_route_from_config(
        public_model,
        endpoint,
        providers=config.providers,
        routes=config.routes,
        environ=environ,
    )


def _resolve_external_model_route_from_config(
    public_model: str | None,
    endpoint: ExternalRouteEndpoint,
    *,
    providers: dict[str, ExternalProviderConfig],
    routes: dict[str, ExternalModelRouteConfig],
    environ: dict[str, str] | None = None,
) -> ExternalRouteResolution:
    if not isinstance(public_model, str) or not public_model.strip():
        return ExternalRouteResolution(ExternalRouteResolutionStatus.NO_ROUTE)

    route = routes.get(public_model.strip())
    if route is None or not route.enabled:
        return ExternalRouteResolution(ExternalRouteResolutionStatus.NO_ROUTE)

    if endpoint not in route.endpoints:
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.ENDPOINT_UNSUPPORTED,
            route=route,
            reason=f"External route for model '{route.public_model}' does not support endpoint '{endpoint}'",
        )

    provider = providers.get(route.provider_id)
    if provider is None or not provider.enabled:
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.PROVIDER_UNAVAILABLE,
            route=route,
            provider=provider,
            reason=f"External provider '{route.provider_id}' is unavailable",
        )

    env = os.environ if environ is None else environ
    env_api_key = env.get(provider.api_key_env) if provider.api_key_env is not None else None
    if not provider.api_key and not env_api_key:
        reason = (
            f"External provider '{provider.id}' API key env '{provider.api_key_env}' is not set"
            if provider.api_key_env is not None
            else f"External provider '{provider.id}' API key is not configured"
        )
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.PROVIDER_UNAVAILABLE,
            route=route,
            provider=provider,
            reason=reason,
        )

    return ExternalRouteResolution(ExternalRouteResolutionStatus.MATCH, route=route, provider=provider)
