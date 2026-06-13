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
    ROUTE_CONFLICT = "route_conflict"


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
        routes=tuple(effective_settings.external_model_routes_json.values()),
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
    routes: tuple[ExternalModelRouteConfig, ...],
    environ: dict[str, str] | None = None,
) -> ExternalRouteResolution:
    if not isinstance(public_model, str) or not public_model.strip():
        return ExternalRouteResolution(ExternalRouteResolutionStatus.NO_ROUTE)

    normalized_model = public_model.strip()
    active_routes = [route for route in routes if route.enabled and route.public_model == normalized_model]
    if not active_routes:
        return ExternalRouteResolution(ExternalRouteResolutionStatus.NO_ROUTE)

    dashboard_matches = [
        route for route in active_routes if route.source == "dashboard" and endpoint in route.endpoints
    ]
    if len(dashboard_matches) > 1:
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.ROUTE_CONFLICT,
            route=dashboard_matches[0],
            reason=f"Multiple active external routes match model '{normalized_model}' and endpoint '{endpoint}'",
        )
    env_matches = [route for route in active_routes if route.source == "env" and endpoint in route.endpoints]
    if dashboard_matches:
        route = dashboard_matches[0]
    elif env_matches:
        route = env_matches[0]
    else:
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.ENDPOINT_UNSUPPORTED,
            route=active_routes[0],
            reason=f"External route for model '{normalized_model}' does not support endpoint '{endpoint}'",
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
