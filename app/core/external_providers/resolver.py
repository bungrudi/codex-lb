from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from app.core.config.settings import Settings, get_settings
from app.core.external_providers.config import ExternalModelRouteConfig, ExternalProviderConfig, ExternalRouteEndpoint


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
    if not isinstance(public_model, str) or not public_model.strip():
        return ExternalRouteResolution(ExternalRouteResolutionStatus.NO_ROUTE)

    effective_settings = settings or get_settings()
    route = effective_settings.external_model_routes_json.get(public_model.strip())
    if route is None or not route.enabled:
        return ExternalRouteResolution(ExternalRouteResolutionStatus.NO_ROUTE)

    if endpoint not in route.endpoints:
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.ENDPOINT_UNSUPPORTED,
            route=route,
            reason=f"External route for model '{route.public_model}' does not support endpoint '{endpoint}'",
        )

    provider = effective_settings.external_providers_json.get(route.provider_id)
    if provider is None or not provider.enabled:
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.PROVIDER_UNAVAILABLE,
            route=route,
            provider=provider,
            reason=f"External provider '{route.provider_id}' is unavailable",
        )

    env = os.environ if environ is None else environ
    if not env.get(provider.api_key_env):
        return ExternalRouteResolution(
            ExternalRouteResolutionStatus.PROVIDER_UNAVAILABLE,
            route=route,
            provider=provider,
            reason=f"External provider '{provider.id}' API key env '{provider.api_key_env}' is not set",
        )

    return ExternalRouteResolution(ExternalRouteResolutionStatus.MATCH, route=route, provider=provider)
