from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

import aiohttp

from app.core.clients.http import lease_http_session
from app.core.errors import OpenAIErrorEnvelope, openai_error
from app.core.external_providers.config import ExternalProviderConfig
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping
from app.core.utils.request_id import get_request_id

logger = logging.getLogger(__name__)

_PROVIDER_DROP_HEADERS = frozenset(
    {
        "authorization",
        "chatgpt-account-id",
        "content-length",
        "host",
        "cookie",
        "proxy-authorization",
        "x-api-key",
    }
)
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


@dataclass(frozen=True, slots=True)
class ExternalProviderError(Exception):
    status_code: int
    payload: OpenAIErrorEnvelope
    provider_id: str
    upstream_error_code: str | None = None

    def __str__(self) -> str:
        error = self.payload.get("error", {})
        message = error.get("message")
        return str(message or f"External provider {self.provider_id} failed with HTTP {self.status_code}")


class OpenAICompatibleProviderClient:
    def __init__(self, provider: ExternalProviderConfig, *, api_key: str | None = None) -> None:
        self._provider = provider
        env_api_key = os.environ.get(provider.api_key_env) if provider.api_key_env is not None else None
        self._api_key = api_key if api_key is not None else provider.api_key or env_api_key
        if not self._api_key:
            raise ExternalProviderError(
                503,
                openai_error(
                    "external_provider_unavailable",
                    f"External provider '{provider.id}' API key is not configured",
                    error_type="server_error",
                ),
                provider_id=provider.id,
                upstream_error_code="external_provider_unavailable",
            )

    async def post_json(
        self,
        endpoint_path: str,
        payload: Mapping[str, JsonValue],
        inbound_headers: Mapping[str, str],
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> dict[str, JsonValue]:
        url = self._url(endpoint_path)
        headers = self._headers(inbound_headers, accept="application/json")
        timeout = aiohttp.ClientTimeout(
            total=self._provider.timeout_seconds, sock_connect=min(30.0, self._provider.timeout_seconds)
        )
        started_at = time.monotonic()
        logger.info(
            "external_provider_request_started request_id=%s provider_id=%s endpoint=%s target_host=%s",
            get_request_id(),
            self._provider.id,
            endpoint_path,
            _target_host(url),
        )
        try:
            async with lease_http_session(session) as client_session:
                async with client_session.post(url, json=dict(payload), headers=headers, timeout=timeout) as response:
                    if response.status >= 400:
                        error_payload = await _error_payload_from_response(response, provider_id=self._provider.id)
                        raise ExternalProviderError(
                            response.status,
                            error_payload,
                            provider_id=self._provider.id,
                            upstream_error_code=_error_code(error_payload),
                        )
                    try:
                        data = await response.json(content_type=None)
                    except Exception as exc:
                        raise _invalid_response_error(
                            self._provider.id, "External provider returned invalid JSON"
                        ) from exc
                    if not is_json_mapping(data):
                        raise _invalid_response_error(
                            self._provider.id,
                            "External provider returned a non-object JSON response",
                        )
                    return dict(data)
        except ExternalProviderError:
            raise
        except asyncio.TimeoutError as exc:
            raise _transport_error(self._provider.id, "External provider request timed out", exc) from exc
        except aiohttp.ClientError as exc:
            message = str(exc) or exc.__class__.__name__
            raise _transport_error(self._provider.id, message, exc) from exc
        finally:
            logger.info(
                "external_provider_request_completed request_id=%s provider_id=%s endpoint=%s latency_ms=%s",
                get_request_id(),
                self._provider.id,
                endpoint_path,
                int((time.monotonic() - started_at) * 1000),
            )

    async def stream_sse(
        self,
        endpoint_path: str,
        payload: Mapping[str, JsonValue],
        inbound_headers: Mapping[str, str],
        *,
        max_event_bytes: int,
        session: aiohttp.ClientSession | None = None,
    ) -> AsyncIterator[str]:
        url = self._url(endpoint_path)
        headers = self._headers(inbound_headers, accept="text/event-stream")
        timeout = aiohttp.ClientTimeout(
            total=self._provider.timeout_seconds,
            sock_connect=min(30.0, self._provider.timeout_seconds),
            sock_read=None,
        )
        started_at = time.monotonic()
        logger.info(
            "external_provider_request_started request_id=%s provider_id=%s endpoint=%s target_host=%s",
            get_request_id(),
            self._provider.id,
            endpoint_path,
            _target_host(url),
        )
        try:
            async with lease_http_session(session) as client_session:
                async with client_session.post(url, json=dict(payload), headers=headers, timeout=timeout) as response:
                    if response.status >= 400:
                        error_payload = await _error_payload_from_response(response, provider_id=self._provider.id)
                        raise ExternalProviderError(
                            response.status,
                            error_payload,
                            provider_id=self._provider.id,
                            upstream_error_code=_error_code(error_payload),
                        )
                    async for event in _iter_sse_events(
                        response,
                        provider_id=self._provider.id,
                        idle_timeout_seconds=self._provider.stream_idle_timeout_seconds,
                        max_event_bytes=max_event_bytes,
                    ):
                        yield event
        except ExternalProviderError:
            raise
        except asyncio.TimeoutError as exc:
            raise _transport_error(self._provider.id, "External provider stream timed out", exc) from exc
        except aiohttp.ClientError as exc:
            message = str(exc) or exc.__class__.__name__
            raise _transport_error(self._provider.id, message, exc) from exc
        finally:
            logger.info(
                "external_provider_request_completed request_id=%s provider_id=%s endpoint=%s latency_ms=%s",
                get_request_id(),
                self._provider.id,
                endpoint_path,
                int((time.monotonic() - started_at) * 1000),
            )

    def _url(self, endpoint_path: str) -> str:
        path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
        return f"{self._provider.base_url.rstrip('/')}{path}"

    def _headers(self, inbound_headers: Mapping[str, str], *, accept: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in inbound_headers.items():
            lower = key.lower()
            if lower in _PROVIDER_DROP_HEADERS or lower in _HOP_BY_HOP_HEADERS:
                continue
            if lower.startswith("x-codex-bridge-"):
                continue
            if lower.startswith("x-forwarded-") or lower.startswith("cf-"):
                continue
            headers[key] = value
        headers.update(self._provider.default_headers)
        headers["Authorization"] = f"Bearer {self._api_key}"
        headers["Accept"] = accept
        headers["Content-Type"] = "application/json"
        return headers


async def _error_payload_from_response(response: aiohttp.ClientResponse, *, provider_id: str) -> OpenAIErrorEnvelope:
    try:
        data = await response.json(content_type=None)
    except Exception:
        text = await response.text()
        message = text[:500] or f"External provider '{provider_id}' returned HTTP {response.status}"
        return _status_error(response.status, message)
    if is_json_mapping(data):
        error = data.get("error")
        if is_json_mapping(error):
            message = error.get("message")
            code = error.get("code")
            error_type = error.get("type")
            return openai_error(
                str(code or _code_for_status(response.status)),
                str(message or f"External provider '{provider_id}' returned HTTP {response.status}"),
                error_type=str(error_type or _type_for_status(response.status)),
            )
        message = data.get("message")
        if isinstance(message, str):
            return _status_error(response.status, message)
    return _status_error(response.status, f"External provider '{provider_id}' returned HTTP {response.status}")


def _status_error(status: int, message: str) -> OpenAIErrorEnvelope:
    return openai_error(_code_for_status(status), message, error_type=_type_for_status(status))


def _code_for_status(status: int) -> str:
    if status == 401:
        return "invalid_api_key"
    if status == 403:
        return "insufficient_permissions"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limit_exceeded"
    if status >= 500:
        return "upstream_unavailable"
    return "invalid_request_error"


def _type_for_status(status: int) -> str:
    if status in {401, 403}:
        return "authentication_error"
    if status == 429:
        return "rate_limit_error"
    if status >= 500:
        return "server_error"
    return "invalid_request_error"


def _error_code(payload: OpenAIErrorEnvelope) -> str | None:
    error = payload.get("error")
    code = error.get("code") if error else None
    return code if isinstance(code, str) else None


def _invalid_response_error(provider_id: str, message: str) -> ExternalProviderError:
    return ExternalProviderError(
        502,
        openai_error(
            "external_provider_invalid_response",
            message,
            error_type="server_error",
        ),
        provider_id=provider_id,
        upstream_error_code="external_provider_invalid_response",
    )


def _transport_error(provider_id: str, message: str, exc: BaseException) -> ExternalProviderError:
    del exc
    return ExternalProviderError(
        503,
        openai_error("external_provider_unavailable", message, error_type="server_error"),
        provider_id=provider_id,
        upstream_error_code="external_provider_unavailable",
    )


async def _iter_sse_events(
    response: aiohttp.ClientResponse,
    *,
    provider_id: str,
    idle_timeout_seconds: float,
    max_event_bytes: int,
) -> AsyncIterator[str]:
    buffer = bytearray()
    iterator = response.content.iter_chunked(4096).__aiter__()
    while True:
        try:
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=idle_timeout_seconds)
        except StopAsyncIteration:
            if buffer:
                yield _decode_event(bytes(buffer))
            return
        if not chunk:
            continue
        buffer.extend(chunk)
        if len(buffer) > max_event_bytes:
            raise ExternalProviderError(
                502,
                openai_error(
                    "stream_event_too_large",
                    "External provider stream event exceeded maximum size",
                    error_type="server_error",
                ),
                provider_id=provider_id,
                upstream_error_code="stream_event_too_large",
            )
        while True:
            marker = _event_boundary(buffer)
            if marker is None:
                break
            event_bytes = bytes(buffer[: marker.end])
            del buffer[: marker.end]
            yield _decode_event(event_bytes)


@dataclass(frozen=True, slots=True)
class _Boundary:
    end: int


def _event_boundary(buffer: bytearray) -> _Boundary | None:
    for separator in (b"\n\n", b"\r\n\r\n"):
        idx = buffer.find(separator)
        if idx >= 0:
            return _Boundary(idx + len(separator))
    return None


def _decode_event(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    if not text.endswith("\n\n"):
        return text.rstrip("\r\n") + "\n\n"
    return text


def _target_host(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc
    except Exception:
        return "unknown"
