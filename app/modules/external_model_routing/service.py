from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence

from app.core.crypto import TokenEncryptor
from app.core.exceptions import DashboardBadRequestError, DashboardConflictError, DashboardNotFoundError
from app.core.external_providers.config import build_external_model_route_config, build_external_provider_config
from app.core.external_providers.runtime_config import get_external_routing_config_cache
from app.core.types import JsonValue
from app.db.models import ExternalModelRoute, ExternalProvider
from app.modules.external_model_routing.repository import ExternalModelRoutingRepository
from app.modules.external_model_routing.schemas import (
    ExternalModelRouteCreateRequest,
    ExternalModelRouteResponse,
    ExternalModelRouteUpdateRequest,
    ExternalModelRoutingAdminResponse,
    ExternalProviderCreateRequest,
    ExternalProviderResponse,
    ExternalProviderSecretSource,
    ExternalProviderUpdateRequest,
    ExternalRouteStatus,
)


class ExternalModelRoutingService:
    def __init__(
        self,
        repository: ExternalModelRoutingRepository,
        *,
        encryptor: TokenEncryptor | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._repository = repository
        self._encryptor = encryptor or TokenEncryptor()
        self._environ = environ if environ is not None else os.environ

    async def get_admin(self) -> ExternalModelRoutingAdminResponse:
        providers = list(await self._repository.list_providers())
        routes = list(await self._repository.list_routes())
        provider_map = {provider.id: provider for provider in providers}
        conflicting_route_ids = _conflicting_active_route_ids(routes)
        return ExternalModelRoutingAdminResponse(
            providers=[self._provider_response(provider) for provider in providers],
            routes=[
                self._route_response(
                    route,
                    provider_map=provider_map,
                    has_active_conflict=route.id in conflicting_route_ids,
                )
                for route in routes
            ],
        )

    async def create_provider(self, payload: ExternalProviderCreateRequest) -> ExternalProviderResponse:
        existing = await self._repository.get_provider(payload.id)
        if existing is not None:
            raise DashboardConflictError("External provider already exists", code="external_provider_exists")
        self._validate_provider_payload(
            provider_id=payload.id,
            kind=payload.kind,
            base_url=payload.base_url,
            api_key_env=payload.api_key_env,
            api_key=payload.api_key,
            default_headers=payload.default_headers,
            timeout_seconds=payload.timeout_seconds,
            stream_idle_timeout_seconds=payload.stream_idle_timeout_seconds,
            enabled=payload.is_active,
            allow_insecure_base_url=payload.allow_insecure_base_url,
        )
        row = ExternalProvider(
            id=payload.id,
            kind=payload.kind,
            base_url=payload.base_url.rstrip("/"),
            api_key_encrypted=self._encryptor.encrypt(payload.api_key) if payload.api_key else None,
            api_key_env=payload.api_key_env,
            default_headers_json=_dump_json_object(payload.default_headers),
            timeout_seconds=payload.timeout_seconds,
            stream_idle_timeout_seconds=payload.stream_idle_timeout_seconds,
            is_active=payload.is_active,
            allow_insecure_base_url=payload.allow_insecure_base_url,
        )
        row = await self._repository.add_provider(row)
        await get_external_routing_config_cache().invalidate()
        return self._provider_response(row)

    async def update_provider(
        self,
        provider_id: str,
        payload: ExternalProviderUpdateRequest,
    ) -> ExternalProviderResponse:
        row = await self._require_provider(provider_id)
        next_kind = payload.kind or row.kind
        next_base_url = (payload.base_url.rstrip("/") if payload.base_url is not None else row.base_url).rstrip("/")
        next_api_key_env = payload.api_key_env if "api_key_env" in payload.model_fields_set else row.api_key_env
        next_default_headers = (
            payload.default_headers
            if payload.default_headers is not None
            else _parse_json_object(row.default_headers_json)
        )
        next_timeout_seconds = payload.timeout_seconds if payload.timeout_seconds is not None else row.timeout_seconds
        next_stream_idle_timeout_seconds = (
            payload.stream_idle_timeout_seconds
            if payload.stream_idle_timeout_seconds is not None
            else row.stream_idle_timeout_seconds
        )
        next_is_active = payload.is_active if payload.is_active is not None else row.is_active
        next_allow_insecure = (
            payload.allow_insecure_base_url
            if payload.allow_insecure_base_url is not None
            else row.allow_insecure_base_url
        )
        candidate_api_key = (
            payload.api_key if payload.api_key is not None else self._safe_decrypt(row.api_key_encrypted)
        )
        if payload.clear_api_key:
            candidate_api_key = None
        self._validate_provider_payload(
            provider_id=row.id,
            kind=next_kind,
            base_url=next_base_url,
            api_key_env=next_api_key_env,
            api_key=candidate_api_key,
            default_headers=next_default_headers,
            timeout_seconds=next_timeout_seconds,
            stream_idle_timeout_seconds=next_stream_idle_timeout_seconds,
            enabled=next_is_active,
            allow_insecure_base_url=next_allow_insecure,
        )
        row.kind = next_kind
        row.base_url = next_base_url
        row.api_key_env = next_api_key_env
        row.default_headers_json = _dump_json_object(next_default_headers)
        row.timeout_seconds = next_timeout_seconds
        row.stream_idle_timeout_seconds = next_stream_idle_timeout_seconds
        row.is_active = next_is_active
        row.allow_insecure_base_url = next_allow_insecure
        if payload.clear_api_key:
            row.api_key_encrypted = None
        elif payload.api_key is not None:
            row.api_key_encrypted = self._encryptor.encrypt(payload.api_key)
        row = await self._repository.save_provider(row)
        await get_external_routing_config_cache().invalidate()
        return self._provider_response(row)

    async def delete_provider(self, provider_id: str) -> None:
        row = await self._require_provider(provider_id)
        await self._repository.delete_provider(row)
        await get_external_routing_config_cache().invalidate()

    async def create_route(self, payload: ExternalModelRouteCreateRequest) -> ExternalModelRouteResponse:
        await self._require_provider(payload.provider_id)
        route_config = self._validate_route_payload(
            public_model=payload.public_model,
            provider_id=payload.provider_id,
            target_model=payload.target_model,
            endpoints=payload.endpoints,
            preserve_public_model=payload.preserve_public_model,
            fallback_to_codex_pool=payload.fallback_to_codex_pool,
            enabled=payload.is_active,
            request_overrides=payload.request_overrides,
            strip_request_fields=payload.strip_request_fields,
            pricing=payload.pricing,
        )
        row = ExternalModelRoute(
            name=payload.name.strip(),
            public_model=route_config.public_model,
            provider_id=route_config.provider_id,
            target_model=route_config.target_model,
            endpoints_json=_dump_string_list(sorted(route_config.endpoints)),
            request_overrides_json=_dump_json_object(route_config.request_overrides),
            strip_request_fields_json=_dump_string_list(sorted(route_config.strip_request_fields)),
            preserve_public_model=route_config.preserve_public_model,
            fallback_to_codex_pool=route_config.fallback_to_codex_pool,
            pricing_json=_dump_json_object(payload.pricing) if payload.pricing is not None else None,
            is_active=route_config.enabled,
        )
        if row.is_active:
            if payload.deactivate_conflicts:
                await self._deactivate_conflicting_routes(
                    public_model=row.public_model,
                    endpoints=route_config.endpoints,
                    exclude_route_id=None,
                )
            else:
                await self._raise_on_active_conflicts(
                    public_model=row.public_model,
                    endpoints=route_config.endpoints,
                    exclude_route_id=None,
                )
        row = await self._repository.add_route(row)
        await get_external_routing_config_cache().invalidate()
        providers = {provider.id: provider for provider in await self._repository.list_providers()}
        conflicting_route_ids = _conflicting_active_route_ids(await self._repository.list_routes())
        return self._route_response(
            row,
            provider_map=providers,
            has_active_conflict=row.id in conflicting_route_ids,
        )

    async def update_route(
        self,
        route_id: str,
        payload: ExternalModelRouteUpdateRequest,
    ) -> ExternalModelRouteResponse:
        row = await self._require_route(route_id)
        next_name = payload.name.strip() if payload.name is not None else row.name
        next_provider_id = payload.provider_id if payload.provider_id is not None else row.provider_id
        await self._require_provider(next_provider_id)
        next_target_model = payload.target_model if payload.target_model is not None else row.target_model
        next_endpoints = payload.endpoints if payload.endpoints is not None else _parse_string_list(row.endpoints_json)
        next_preserve_public_model = (
            payload.preserve_public_model if payload.preserve_public_model is not None else row.preserve_public_model
        )
        next_fallback = payload.fallback_to_codex_pool if payload.fallback_to_codex_pool is not None else False
        next_is_active = payload.is_active if payload.is_active is not None else row.is_active
        next_request_overrides = (
            payload.request_overrides
            if payload.request_overrides is not None
            else _parse_json_object(row.request_overrides_json)
        )
        next_strip_fields = (
            payload.strip_request_fields
            if payload.strip_request_fields is not None
            else _parse_string_list(row.strip_request_fields_json)
        )
        next_pricing = (
            payload.pricing if "pricing" in payload.model_fields_set else _parse_optional_json_object(row.pricing_json)
        )
        route_config = self._validate_route_payload(
            public_model=row.public_model,
            provider_id=next_provider_id,
            target_model=next_target_model,
            endpoints=next_endpoints,
            preserve_public_model=next_preserve_public_model,
            fallback_to_codex_pool=next_fallback,
            enabled=next_is_active,
            request_overrides=next_request_overrides,
            strip_request_fields=next_strip_fields,
            pricing=next_pricing,
        )
        row.name = next_name
        row.provider_id = route_config.provider_id
        row.target_model = route_config.target_model
        row.endpoints_json = _dump_string_list(sorted(route_config.endpoints))
        row.request_overrides_json = _dump_json_object(route_config.request_overrides)
        row.strip_request_fields_json = _dump_string_list(sorted(route_config.strip_request_fields))
        row.preserve_public_model = route_config.preserve_public_model
        row.fallback_to_codex_pool = route_config.fallback_to_codex_pool
        row.pricing_json = _dump_json_object(next_pricing) if next_pricing is not None else None
        row.is_active = route_config.enabled
        if row.is_active:
            if payload.deactivate_conflicts:
                await self._deactivate_conflicting_routes(
                    public_model=row.public_model,
                    endpoints=route_config.endpoints,
                    exclude_route_id=row.id,
                )
            else:
                await self._raise_on_active_conflicts(
                    public_model=row.public_model,
                    endpoints=route_config.endpoints,
                    exclude_route_id=row.id,
                )
        row = await self._repository.save_route(row)
        await get_external_routing_config_cache().invalidate()
        providers = {provider.id: provider for provider in await self._repository.list_providers()}
        conflicting_route_ids = _conflicting_active_route_ids(await self._repository.list_routes())
        return self._route_response(
            row,
            provider_map=providers,
            has_active_conflict=row.id in conflicting_route_ids,
        )

    async def delete_route(self, route_id: str) -> None:
        row = await self._require_route(route_id)
        await self._repository.delete_route(row)
        await get_external_routing_config_cache().invalidate()

    async def _require_provider(self, provider_id: str) -> ExternalProvider:
        row = await self._repository.get_provider(provider_id.strip().lower())
        if row is None:
            raise DashboardNotFoundError("External provider not found", code="external_provider_not_found")
        return row

    async def _require_route(self, route_id: str) -> ExternalModelRoute:
        row = await self._repository.get_route(route_id.strip())
        if row is None:
            raise DashboardNotFoundError("External model route not found", code="external_model_route_not_found")
        return row

    async def _deactivate_conflicting_routes(
        self,
        *,
        public_model: str,
        endpoints: frozenset[str],
        exclude_route_id: str | None,
    ) -> None:
        for route in await self._repository.list_routes():
            if route.public_model != public_model or route.id == exclude_route_id or not route.is_active:
                continue
            if endpoints.intersection(_parse_string_list(route.endpoints_json)):
                route.is_active = False

    async def _raise_on_active_conflicts(
        self,
        *,
        public_model: str,
        endpoints: frozenset[str],
        exclude_route_id: str | None,
    ) -> None:
        for route in await self._repository.list_routes():
            if route.public_model != public_model or route.id == exclude_route_id or not route.is_active:
                continue
            if endpoints.intersection(_parse_string_list(route.endpoints_json)):
                raise DashboardConflictError(
                    "External model route profile conflicts with an active profile for this endpoint",
                    code="external_model_route_conflict",
                )

    def _validate_provider_payload(
        self,
        *,
        provider_id: str,
        kind: str,
        base_url: str,
        api_key_env: str | None,
        api_key: str | None,
        default_headers: dict[str, str],
        timeout_seconds: float,
        stream_idle_timeout_seconds: float,
        enabled: bool,
        allow_insecure_base_url: bool,
    ) -> None:
        try:
            build_external_provider_config(
                provider_id=provider_id,
                kind=kind,
                base_url=base_url,
                api_key_env=api_key_env,
                api_key=api_key,
                default_headers=default_headers,
                timeout_seconds=timeout_seconds,
                stream_idle_timeout_seconds=stream_idle_timeout_seconds,
                enabled=enabled,
                allow_insecure_base_url=allow_insecure_base_url,
            )
        except (TypeError, ValueError) as exc:
            raise DashboardBadRequestError(str(exc), code="invalid_external_provider") from exc

    def _validate_route_payload(
        self,
        *,
        public_model: str,
        provider_id: str,
        target_model: str,
        endpoints: list[str],
        preserve_public_model: bool,
        fallback_to_codex_pool: bool,
        enabled: bool,
        request_overrides: dict[str, JsonValue],
        strip_request_fields: list[str],
        pricing: dict[str, JsonValue] | None,
    ):
        try:
            return build_external_model_route_config(
                public_model=public_model,
                provider_id=provider_id,
                target_model=target_model,
                endpoints=endpoints,
                preserve_public_model=preserve_public_model,
                fallback_to_codex_pool=fallback_to_codex_pool,
                enabled=enabled,
                request_overrides=request_overrides,
                strip_request_fields=strip_request_fields,
                pricing=pricing,
            )
        except (TypeError, ValueError) as exc:
            raise DashboardBadRequestError(str(exc), code="invalid_external_model_route") from exc

    def _provider_response(self, row: ExternalProvider) -> ExternalProviderResponse:
        api_key_source = self._provider_api_key_source(row)
        return ExternalProviderResponse(
            id=row.id,
            kind="openai_compatible",
            base_url=row.base_url,
            api_key_configured=api_key_source != "missing",
            api_key_source=api_key_source,
            api_key_env=row.api_key_env,
            default_headers=_parse_json_string_map(row.default_headers_json),
            timeout_seconds=row.timeout_seconds,
            stream_idle_timeout_seconds=row.stream_idle_timeout_seconds,
            is_active=row.is_active,
            allow_insecure_base_url=row.allow_insecure_base_url,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _route_response(
        self,
        row: ExternalModelRoute,
        *,
        provider_map: Mapping[str, ExternalProvider],
        has_active_conflict: bool = False,
    ) -> ExternalModelRouteResponse:
        status, status_message = self._route_status(
            row,
            provider_map=provider_map,
            has_active_conflict=has_active_conflict,
        )
        return ExternalModelRouteResponse(
            id=row.id,
            name=row.name,
            public_model=row.public_model,
            provider_id=row.provider_id,
            target_model=row.target_model,
            endpoints=_parse_string_list(row.endpoints_json),
            preserve_public_model=row.preserve_public_model,
            fallback_to_codex_pool=row.fallback_to_codex_pool,
            is_active=row.is_active,
            request_overrides=_parse_json_object(row.request_overrides_json),
            strip_request_fields=_parse_string_list(row.strip_request_fields_json),
            pricing=_parse_optional_json_object(row.pricing_json),
            status=status,
            status_message=status_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _route_status(
        self,
        row: ExternalModelRoute,
        *,
        provider_map: Mapping[str, ExternalProvider],
        has_active_conflict: bool = False,
    ) -> tuple[ExternalRouteStatus, str | None]:
        if not row.is_active:
            return "disabled", "Route is disabled"
        if has_active_conflict:
            return "conflict", "Multiple active route profiles match at least one endpoint"
        provider = provider_map.get(row.provider_id)
        if provider is None or not provider.is_active:
            return "provider_disabled", "Provider is missing or disabled"
        if self._provider_api_key_source(provider) == "missing":
            return "missing_api_key", "Provider API key is not configured"
        return "active", None

    def _provider_api_key_source(self, row: ExternalProvider) -> ExternalProviderSecretSource:
        if row.api_key_encrypted is not None:
            return "dashboard"
        if row.api_key_env and self._environ.get(row.api_key_env):
            return "env"
        return "missing"

    def _safe_decrypt(self, encrypted: bytes | None) -> str | None:
        if encrypted is None:
            return None
        return self._encryptor.decrypt(encrypted)


def _conflicting_active_route_ids(routes: Sequence[ExternalModelRoute]) -> set[str]:
    route_ids_by_endpoint: dict[tuple[str, str], list[str]] = {}
    for route in routes:
        if not route.is_active:
            continue
        for endpoint in _parse_string_list(route.endpoints_json):
            route_ids_by_endpoint.setdefault((route.public_model, endpoint), []).append(route.id)

    conflicting_ids: set[str] = set()
    for route_ids in route_ids_by_endpoint.values():
        if len(route_ids) > 1:
            conflicting_ids.update(route_ids)
    return conflicting_ids


def _dump_json_object(value: Mapping[str, JsonValue] | None) -> str:
    return json.dumps(dict(value or {}), sort_keys=True, separators=(",", ":"))


def _dump_string_list(value: Sequence[str]) -> str:
    return json.dumps(list(value), separators=(",", ":"))


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


def _parse_json_string_map(raw: str | None) -> dict[str, str]:
    parsed = _parse_json_object(raw)
    return {str(key): str(value) for key, value in parsed.items()}


def _parse_string_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("stored JSON list is invalid")
    result: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result
