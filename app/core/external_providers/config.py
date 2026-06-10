from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping

type ExternalProviderKind = Literal["openai_compatible"]
type ExternalRouteEndpoint = Literal[
    "chat.completions",
    "responses",
    "responses.stream",
    "responses.collect",
    "responses.compact",
    "responses.websocket",
    "backend.responses",
    "audio.transcriptions",
    "images.generations",
    "images.edits",
]
type ExternalPricingMode = Literal["none", "public_model", "provider_custom"]

EXTERNAL_PROVIDER_ENDPOINTS: frozenset[str] = frozenset(
    {
        "chat.completions",
        "responses",
        "responses.stream",
        "responses.collect",
        "responses.compact",
        "responses.websocket",
        "backend.responses",
        "audio.transcriptions",
        "images.generations",
        "images.edits",
    }
)
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ExternalProviderPricing:
    mode: ExternalPricingMode = "none"
    input_per_1m: float | None = None
    output_per_1m: float | None = None
    cached_input_per_1m: float | None = None


@dataclass(frozen=True, slots=True)
class ExternalProviderConfig:
    id: str
    kind: ExternalProviderKind
    base_url: str
    api_key_env: str | None
    default_headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 600.0
    stream_idle_timeout_seconds: float = 600.0
    enabled: bool = True
    allow_insecure_base_url: bool = False
    api_key: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ExternalModelRouteConfig:
    public_model: str
    provider_id: str
    target_model: str
    endpoints: frozenset[ExternalRouteEndpoint]
    preserve_public_model: bool = True
    fallback_to_codex_pool: bool = False
    enabled: bool = True
    request_overrides: dict[str, JsonValue] = field(default_factory=dict)
    strip_request_fields: frozenset[str] = frozenset()
    pricing: ExternalProviderPricing | None = None


def build_external_provider_config(
    *,
    provider_id: str,
    kind: str = "openai_compatible",
    base_url: str,
    api_key_env: str | None = None,
    api_key: str | None = None,
    default_headers: dict[str, str] | None = None,
    timeout_seconds: float = 600.0,
    stream_idle_timeout_seconds: float = 600.0,
    enabled: bool = True,
    allow_insecure_base_url: bool = False,
) -> ExternalProviderConfig:
    normalized_id = _normalize_provider_id(provider_id)
    if kind != "openai_compatible":
        raise ValueError(f"external provider '{provider_id}' kind must be 'openai_compatible'")
    normalized_base_url = _required_string(base_url, f"external provider '{provider_id}'.base_url").rstrip("/")
    _validate_base_url(normalized_base_url, allow_insecure=allow_insecure_base_url, provider_id=normalized_id)
    normalized_api_key_env: str | None = None
    if api_key_env is not None and api_key_env.strip():
        normalized_api_key_env = _required_string(api_key_env, f"external provider '{provider_id}'.api_key_env")
        _validate_env_name(normalized_api_key_env, provider_id=normalized_id)
    return ExternalProviderConfig(
        id=normalized_id,
        kind="openai_compatible",
        base_url=normalized_base_url,
        api_key_env=normalized_api_key_env,
        default_headers=default_headers or {},
        timeout_seconds=_positive_float(timeout_seconds, f"external provider '{provider_id}'.timeout_seconds"),
        stream_idle_timeout_seconds=_positive_float(
            stream_idle_timeout_seconds,
            f"external provider '{provider_id}'.stream_idle_timeout_seconds",
        ),
        enabled=enabled,
        allow_insecure_base_url=allow_insecure_base_url,
        api_key=api_key.strip() if isinstance(api_key, str) and api_key.strip() else None,
    )


def build_external_model_route_config(
    *,
    public_model: str,
    provider_id: str,
    target_model: str,
    endpoints: list[str] | str,
    preserve_public_model: bool = True,
    fallback_to_codex_pool: bool = False,
    enabled: bool = True,
    request_overrides: dict[str, JsonValue] | None = None,
    strip_request_fields: list[str] | str | None = None,
    pricing: JsonValue = None,
) -> ExternalModelRouteConfig:
    normalized_public_model = _normalize_model_id(public_model, field_name="external route public model")
    if fallback_to_codex_pool:
        raise ValueError(f"external route '{normalized_public_model}' fallback_to_codex_pool is not supported yet")
    strip_fields_value = strip_request_fields if strip_request_fields is not None else []
    return ExternalModelRouteConfig(
        public_model=normalized_public_model,
        provider_id=_normalize_provider_id(provider_id),
        target_model=_normalize_model_id(target_model, field_name=f"external route '{public_model}'.target_model"),
        endpoints=_parse_endpoints(endpoints, public_model=normalized_public_model),
        preserve_public_model=preserve_public_model,
        fallback_to_codex_pool=fallback_to_codex_pool,
        enabled=enabled,
        request_overrides=_json_mapping_value(request_overrides or {}, field_name="request_overrides"),
        strip_request_fields=frozenset(_string_list(strip_fields_value, field_name="strip_request_fields")),
        pricing=_parse_pricing(pricing, public_model=normalized_public_model),
    )


def parse_external_provider_configs(value: JsonValue) -> dict[str, ExternalProviderConfig]:
    raw = _parse_json_object(value, field_name="external_providers_json")
    providers: dict[str, ExternalProviderConfig] = {}
    for provider_id, item in raw.items():
        normalized_id = _normalize_provider_id(provider_id)
        if not is_json_mapping(item):
            raise TypeError(f"external provider '{provider_id}' must be an object")
        data = dict(item)
        explicit_id = data.pop("id", normalized_id)
        if (
            _normalize_provider_id(_required_string(explicit_id, f"external provider '{provider_id}'.id"))
            != normalized_id
        ):
            raise ValueError(f"external provider '{provider_id}' id must match its map key")
        kind_value = data.pop("kind", "openai_compatible")
        if kind_value != "openai_compatible":
            raise ValueError(f"external provider '{provider_id}' kind must be 'openai_compatible'")
        base_url = _required_string(data.pop("base_url", None), f"external provider '{provider_id}'.base_url").rstrip(
            "/"
        )
        allow_insecure = bool(data.pop("allow_insecure_base_url", False))
        _validate_base_url(base_url, allow_insecure=allow_insecure, provider_id=normalized_id)
        api_key_env = _required_string(data.pop("api_key_env", None), f"external provider '{provider_id}'.api_key_env")
        _validate_env_name(api_key_env, provider_id=normalized_id)
        default_headers = _string_mapping(
            data.pop("default_headers", {}), f"external provider '{provider_id}'.default_headers"
        )
        providers[normalized_id] = ExternalProviderConfig(
            id=normalized_id,
            kind="openai_compatible",
            base_url=base_url,
            api_key_env=api_key_env,
            default_headers=default_headers,
            timeout_seconds=_positive_float(
                data.pop("timeout_seconds", 600.0), f"external provider '{provider_id}'.timeout_seconds"
            ),
            stream_idle_timeout_seconds=_positive_float(
                data.pop("stream_idle_timeout_seconds", 600.0),
                f"external provider '{provider_id}'.stream_idle_timeout_seconds",
            ),
            enabled=bool(data.pop("enabled", True)),
            allow_insecure_base_url=allow_insecure,
        )
    return providers


def parse_external_model_route_configs(value: JsonValue) -> dict[str, ExternalModelRouteConfig]:
    raw = _parse_json_object(value, field_name="external_model_routes_json")
    routes: dict[str, ExternalModelRouteConfig] = {}
    for public_model_key, item in raw.items():
        public_model = _normalize_model_id(public_model_key, field_name="external route public model")
        if not is_json_mapping(item):
            raise TypeError(f"external route '{public_model_key}' must be an object")
        data = dict(item)
        explicit_public_model = data.pop("public_model", public_model)
        if (
            _normalize_model_id(explicit_public_model, field_name=f"external route '{public_model_key}'.public_model")
            != public_model
        ):
            raise ValueError(f"external route '{public_model_key}' public_model must match its map key")
        provider_id = _normalize_provider_id(
            _required_string(data.pop("provider_id", None), f"external route '{public_model_key}'.provider_id")
        )
        target_model = _normalize_model_id(
            data.pop("target_model", None), field_name=f"external route '{public_model_key}'.target_model"
        )
        endpoints = _parse_endpoints(data.pop("endpoints", ["chat.completions"]), public_model=public_model)
        fallback_to_codex_pool = bool(data.pop("fallback_to_codex_pool", False))
        if fallback_to_codex_pool:
            raise ValueError(f"external route '{public_model_key}' fallback_to_codex_pool is not supported yet")
        routes[public_model] = ExternalModelRouteConfig(
            public_model=public_model,
            provider_id=provider_id,
            target_model=target_model,
            endpoints=endpoints,
            preserve_public_model=bool(data.pop("preserve_public_model", True)),
            fallback_to_codex_pool=fallback_to_codex_pool,
            enabled=bool(data.pop("enabled", True)),
            request_overrides=_json_mapping_value(data.pop("request_overrides", {}), field_name="request_overrides"),
            strip_request_fields=frozenset(
                _string_list(data.pop("strip_request_fields", []), field_name="strip_request_fields")
            ),
            pricing=_parse_pricing(data.pop("pricing", None), public_model=public_model),
        )
    return routes


def validate_external_routes_reference_providers(
    routes: dict[str, ExternalModelRouteConfig],
    providers: dict[str, ExternalProviderConfig],
) -> None:
    for public_model, route in routes.items():
        if not route.enabled:
            continue
        if route.provider_id not in providers:
            raise ValueError(f"external route '{public_model}' references unknown provider '{route.provider_id}'")


def _parse_json_object(value: JsonValue, *, field_name: str) -> dict[str, JsonValue]:
    if value is None:
        return {}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        parsed = json.loads(stripped)
        if not is_json_mapping(parsed):
            raise TypeError(f"{field_name} must be a JSON object")
        return dict(parsed)
    if is_json_mapping(value):
        return dict(value)
    raise TypeError(f"{field_name} must be a JSON object")


def _normalize_provider_id(value: str) -> str:
    normalized = value.strip().lower()
    if not _PROVIDER_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid external provider id: {value!r}")
    return normalized


def _normalize_model_id(value: JsonValue, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _required_string(value: JsonValue, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


def _validate_base_url(base_url: str, *, allow_insecure: bool, provider_id: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError(f"external provider '{provider_id}' base_url must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and not allow_insecure:
        raise ValueError(f"external provider '{provider_id}' base_url must use https")


def _validate_env_name(api_key_env: str, *, provider_id: str) -> None:
    if not _ENV_NAME_PATTERN.fullmatch(api_key_env):
        raise ValueError(f"external provider '{provider_id}' api_key_env must be a valid environment variable name")


def _string_mapping(value: JsonValue, field_name: str) -> dict[str, str]:
    if not is_json_mapping(value):
        raise TypeError(f"{field_name} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise TypeError(f"{field_name}.{key} must be a string")
        result[str(key)] = item
    return result


def _positive_float(value: JsonValue, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a positive number")
    result = float(value)
    if result <= 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _parse_endpoints(value: JsonValue, *, public_model: str) -> frozenset[ExternalRouteEndpoint]:
    endpoints = _string_list(value, field_name=f"external route '{public_model}'.endpoints")
    if not endpoints:
        raise ValueError(f"external route '{public_model}' must include at least one endpoint")
    invalid = [endpoint for endpoint in endpoints if endpoint not in EXTERNAL_PROVIDER_ENDPOINTS]
    if invalid:
        raise ValueError(f"external route '{public_model}' has unsupported endpoint(s): {', '.join(invalid)}")
    return frozenset(endpoints)  # type: ignore[arg-type]


def _string_list(value: JsonValue, *, field_name: str) -> list[str]:
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        items = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError(f"{field_name} entries must be strings")
            items.append(item.strip())
    else:
        raise TypeError(f"{field_name} must be a list or comma-separated string")
    return [item for item in items if item]


def _json_mapping_value(value: JsonValue, *, field_name: str) -> dict[str, JsonValue]:
    if not is_json_mapping(value):
        raise TypeError(f"{field_name} must be an object")
    return dict(value)


def _parse_pricing(value: JsonValue, *, public_model: str) -> ExternalProviderPricing | None:
    if value is None:
        return None
    if not is_json_mapping(value):
        raise TypeError(f"external route '{public_model}'.pricing must be an object")
    data = dict(value)
    mode = data.get("mode", "none")
    if mode not in {"none", "public_model", "provider_custom"}:
        raise ValueError(f"external route '{public_model}'.pricing.mode is invalid")
    return ExternalProviderPricing(
        mode=mode,  # type: ignore[arg-type]
        input_per_1m=_optional_non_negative_float(data.get("input_per_1m"), "input_per_1m"),
        output_per_1m=_optional_non_negative_float(data.get("output_per_1m"), "output_per_1m"),
        cached_input_per_1m=_optional_non_negative_float(data.get("cached_input_per_1m"), "cached_input_per_1m"),
    )


def _optional_non_negative_float(value: JsonValue, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"pricing.{field_name} must be a non-negative number")
    result = float(value)
    if result < 0:
        raise ValueError(f"pricing.{field_name} must be non-negative")
    return result
