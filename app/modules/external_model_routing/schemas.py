from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.core.external_providers.config import EXTERNAL_PROVIDER_ENDPOINTS
from app.core.types import JsonValue
from app.modules.shared.schemas import DashboardModel

ExternalProviderSecretSource = Literal["dashboard", "env", "missing"]
ExternalRouteStatus = Literal["active", "disabled", "provider_disabled", "missing_api_key"]
ExternalProviderKindValue = Literal["openai_compatible"]

_CREDENTIAL_HEADER_NAMES = frozenset({"authorization", "x-api-key", "proxy-authorization", "cookie", "set-cookie"})
_PROVIDER_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class ExternalProviderCreateRequest(DashboardModel):
    id: str = Field(pattern=_PROVIDER_ID_PATTERN)
    kind: ExternalProviderKindValue = "openai_compatible"
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, max_length=8192)
    api_key_env: str | None = Field(default=None, max_length=128)
    default_headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=600.0, gt=0)
    stream_idle_timeout_seconds: float = Field(default=600.0, gt=0)
    is_active: bool = True
    allow_insecure_base_url: bool = False

    @field_validator("id")
    @classmethod
    def _normalize_id(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("base_url", "api_key_env")
    @classmethod
    def _strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("api_key")
    @classmethod
    def _strip_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("default_headers")
    @classmethod
    def _validate_default_headers(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_default_headers(value)


class ExternalProviderUpdateRequest(DashboardModel):
    kind: ExternalProviderKindValue | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, max_length=8192)
    clear_api_key: bool = False
    api_key_env: str | None = Field(default=None, max_length=128)
    default_headers: dict[str, str] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    stream_idle_timeout_seconds: float | None = Field(default=None, gt=0)
    is_active: bool | None = None
    allow_insecure_base_url: bool | None = None

    @field_validator("base_url", "api_key_env")
    @classmethod
    def _strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("api_key")
    @classmethod
    def _strip_api_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("default_headers")
    @classmethod
    def _validate_default_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        return _validate_default_headers(value)

    @model_validator(mode="after")
    def _validate_secret_update(self) -> "ExternalProviderUpdateRequest":
        if self.api_key and self.clear_api_key:
            raise ValueError("api_key and clear_api_key cannot both be provided")
        return self


class ExternalProviderResponse(DashboardModel):
    id: str
    kind: ExternalProviderKindValue
    base_url: str
    api_key_configured: bool
    api_key_source: ExternalProviderSecretSource
    api_key_env: str | None
    default_headers: dict[str, str]
    timeout_seconds: float
    stream_idle_timeout_seconds: float
    is_active: bool
    allow_insecure_base_url: bool
    created_at: datetime
    updated_at: datetime


class ExternalModelRouteCreateRequest(DashboardModel):
    public_model: str = Field(min_length=1, max_length=255)
    provider_id: str = Field(pattern=_PROVIDER_ID_PATTERN)
    target_model: str = Field(min_length=1, max_length=255)
    endpoints: list[str] = Field(min_length=1)
    preserve_public_model: bool = True
    fallback_to_codex_pool: bool = False
    is_active: bool = True
    request_overrides: dict[str, JsonValue] = Field(default_factory=dict)
    strip_request_fields: list[str] = Field(default_factory=list)
    pricing: dict[str, JsonValue] | None = None

    @field_validator("public_model", "provider_id", "target_model")
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("provider_id")
    @classmethod
    def _normalize_provider_id(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("endpoints")
    @classmethod
    def _validate_endpoints(cls, value: list[str]) -> list[str]:
        return _validate_endpoints(value)

    @field_validator("strip_request_fields")
    @classmethod
    def _validate_strip_fields(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value)

    @model_validator(mode="after")
    def _reject_fallback(self) -> "ExternalModelRouteCreateRequest":
        if self.fallback_to_codex_pool:
            raise ValueError("fallback_to_codex_pool is not supported yet")
        return self


class ExternalModelRouteUpdateRequest(DashboardModel):
    provider_id: str | None = Field(default=None, pattern=_PROVIDER_ID_PATTERN)
    target_model: str | None = Field(default=None, min_length=1, max_length=255)
    endpoints: list[str] | None = Field(default=None, min_length=1)
    preserve_public_model: bool | None = None
    fallback_to_codex_pool: bool | None = None
    is_active: bool | None = None
    request_overrides: dict[str, JsonValue] | None = None
    strip_request_fields: list[str] | None = None
    pricing: dict[str, JsonValue] | None = None

    @field_validator("provider_id", "target_model")
    @classmethod
    def _strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("provider_id")
    @classmethod
    def _normalize_provider_id(cls, value: str | None) -> str | None:
        return value.strip().lower() if value is not None else None

    @field_validator("endpoints")
    @classmethod
    def _validate_optional_endpoints(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _validate_endpoints(value)

    @field_validator("strip_request_fields")
    @classmethod
    def _validate_optional_strip_fields(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_string_list(value)

    @model_validator(mode="after")
    def _reject_fallback(self) -> "ExternalModelRouteUpdateRequest":
        if self.fallback_to_codex_pool:
            raise ValueError("fallback_to_codex_pool is not supported yet")
        return self


class ExternalModelRouteResponse(DashboardModel):
    public_model: str
    provider_id: str
    target_model: str
    endpoints: list[str]
    preserve_public_model: bool
    fallback_to_codex_pool: bool
    is_active: bool
    request_overrides: dict[str, JsonValue]
    strip_request_fields: list[str]
    pricing: dict[str, JsonValue] | None
    status: ExternalRouteStatus
    status_message: str | None
    created_at: datetime
    updated_at: datetime


class ExternalModelRoutingAdminResponse(DashboardModel):
    providers: list[ExternalProviderResponse]
    routes: list[ExternalModelRouteResponse]


def _validate_default_headers(value: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, item in value.items():
        header_name = key.strip()
        if not header_name:
            raise ValueError("default header names must not be blank")
        if header_name.lower() in _CREDENTIAL_HEADER_NAMES:
            raise ValueError(f"default header '{header_name}' is credential-bearing and cannot be stored")
        if not isinstance(item, str):
            raise ValueError(f"default header '{header_name}' must be a string")
        normalized[header_name] = item
    return normalized


def _validate_endpoints(value: list[str]) -> list[str]:
    normalized = _normalize_string_list(value)
    if not normalized:
        raise ValueError("endpoints must include at least one endpoint")
    invalid = [endpoint for endpoint in normalized if endpoint not in EXTERNAL_PROVIDER_ENDPOINTS]
    if invalid:
        raise ValueError(f"unsupported external route endpoint(s): {', '.join(invalid)}")
    return list(dict.fromkeys(normalized))


def _normalize_string_list(value: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in value:
        stripped = item.strip()
        if stripped:
            normalized.append(stripped)
    return normalized
