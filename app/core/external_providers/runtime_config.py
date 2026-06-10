from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import anyio
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.core.external_providers.config import (
    ExternalModelRouteConfig,
    ExternalProviderConfig,
    build_external_model_route_config,
    build_external_provider_config,
)
from app.core.types import JsonValue
from app.db.models import ExternalModelRoute, ExternalProvider
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EffectiveExternalRoutingConfig:
    providers: dict[str, ExternalProviderConfig]
    routes: tuple[ExternalModelRouteConfig, ...]


class ExternalRoutingConfigCache:
    def __init__(self, *, ttl_seconds: float = 5.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._cached_config: EffectiveExternalRoutingConfig | None = None
        self._cached_at = 0.0
        self._lock = anyio.Lock()

    async def get(self) -> EffectiveExternalRoutingConfig:
        now = time.monotonic()
        if self._cached_config is not None and now - self._cached_at < self._ttl_seconds:
            return self._cached_config

        async with self._lock:
            now = time.monotonic()
            if self._cached_config is not None and now - self._cached_at < self._ttl_seconds:
                return self._cached_config
            config = await load_effective_external_routing_config()
            self._cached_config = config
            self._cached_at = now
            return config

    async def invalidate(self) -> None:
        async with self._lock:
            self._cached_config = None
            self._cached_at = 0.0


_external_routing_config_cache = ExternalRoutingConfigCache()


def get_external_routing_config_cache() -> ExternalRoutingConfigCache:
    return _external_routing_config_cache


async def load_effective_external_routing_config() -> EffectiveExternalRoutingConfig:
    settings = get_settings()
    providers = dict(settings.external_providers_json)
    env_routes = tuple(settings.external_model_routes_json.values())
    dashboard_config = await load_dashboard_external_routing_config()
    providers.update(dashboard_config.providers)
    dashboard_route_keys = {
        (route.public_model, endpoint)
        for route in dashboard_config.routes
        if route.enabled
        for endpoint in route.endpoints
    }
    effective_env_routes = tuple(
        route
        for route in env_routes
        if not any((route.public_model, endpoint) in dashboard_route_keys for endpoint in route.endpoints)
    )
    routes = (*dashboard_config.routes, *effective_env_routes)
    return EffectiveExternalRoutingConfig(providers=providers, routes=routes)


async def load_dashboard_external_routing_config() -> EffectiveExternalRoutingConfig:
    encryptor = TokenEncryptor()
    providers: dict[str, ExternalProviderConfig] = {}
    routes: list[ExternalModelRouteConfig] = []
    try:
        async with SessionLocal() as session:
            provider_rows = (
                await session.execute(select(ExternalProvider).order_by(ExternalProvider.id.asc()))
            ).scalars()
            for row in provider_rows:
                provider = _provider_config_from_row(row, encryptor=encryptor)
                if provider is not None:
                    providers[provider.id] = provider
            route_rows = (
                await session.execute(select(ExternalModelRoute).order_by(ExternalModelRoute.public_model.asc()))
            ).scalars()
            for row in route_rows:
                route = _route_config_from_row(row)
                if route is not None:
                    routes.append(route)
    except SQLAlchemyError:
        logger.warning("Dashboard external routing config unavailable; using environment config only", exc_info=True)
    return EffectiveExternalRoutingConfig(providers=providers, routes=tuple(routes))


def _provider_config_from_row(
    row: ExternalProvider,
    *,
    encryptor: TokenEncryptor,
) -> ExternalProviderConfig | None:
    api_key: str | None = None
    if row.api_key_encrypted is not None:
        api_key = encryptor.decrypt(row.api_key_encrypted)
    try:
        return build_external_provider_config(
            provider_id=row.id,
            kind=row.kind,
            base_url=row.base_url,
            api_key_env=row.api_key_env,
            api_key=api_key,
            default_headers=_parse_string_map(row.default_headers_json),
            timeout_seconds=row.timeout_seconds,
            stream_idle_timeout_seconds=row.stream_idle_timeout_seconds,
            enabled=row.is_active,
            allow_insecure_base_url=row.allow_insecure_base_url,
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Skipping invalid dashboard external provider %s: %s", row.id, exc)
        return None


def _route_config_from_row(row: ExternalModelRoute) -> ExternalModelRouteConfig | None:
    try:
        return build_external_model_route_config(
            public_model=row.public_model,
            provider_id=row.provider_id,
            target_model=row.target_model,
            endpoints=_parse_string_list(row.endpoints_json),
            preserve_public_model=row.preserve_public_model,
            fallback_to_codex_pool=row.fallback_to_codex_pool,
            enabled=row.is_active,
            request_overrides=_parse_json_object(row.request_overrides_json),
            strip_request_fields=_parse_string_list(row.strip_request_fields_json),
            pricing=_parse_optional_json_object(row.pricing_json),
            route_id=row.id,
            name=row.name,
            source="dashboard",
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Skipping invalid dashboard external route %s: %s", row.public_model, exc)
        return None


def _parse_json_object(raw: str | None) -> dict[str, JsonValue]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("stored JSON object is invalid")
    return dict(parsed)


def _parse_optional_json_object(raw: str | None) -> dict[str, JsonValue] | None:
    if raw is None:
        return None
    return _parse_json_object(raw)


def _parse_string_map(raw: str | None) -> dict[str, str]:
    parsed = _parse_json_object(raw)
    result: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(value, str):
            raise ValueError(f"stored header '{key}' is not a string")
        result[str(key)] = value
    return result


def _parse_string_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("stored JSON list is invalid")
    result: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            raise ValueError("stored JSON list entries must be strings")
        stripped = item.strip()
        if stripped:
            result.append(stripped)
    return result
