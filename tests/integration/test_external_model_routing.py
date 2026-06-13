from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

import pytest

import app.modules.proxy.api as proxy_api
from app.core.config.settings import get_settings
from app.core.errors import openai_error
from app.core.external_providers.openai_compatible import ExternalProviderError
from app.core.types import JsonValue

pytestmark = pytest.mark.integration


async def _enable_api_key_auth(async_client) -> None:
    response = await async_client.put(
        "/api/settings",
        json={
            "stickyThreadsEnabled": False,
            "preferEarlierResetAccounts": False,
            "totpRequiredOnLogin": False,
            "apiKeyAuthEnabled": True,
        },
    )
    assert response.status_code == 200


def _configure_external_route(monkeypatch: pytest.MonkeyPatch, *, endpoints: list[str] | None = None) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv(
        "CODEX_LB_EXTERNAL_PROVIDERS_JSON",
        json.dumps(
            {
                "openrouter": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                }
            }
        ),
    )
    monkeypatch.setenv(
        "CODEX_LB_EXTERNAL_MODEL_ROUTES_JSON",
        json.dumps(
            {
                "gpt-5.3-codex": {
                    "provider_id": "openrouter",
                    "target_model": "minimax/minimax-m3",
                    "endpoints": endpoints or ["chat.completions"],
                }
            }
        ),
    )
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_v1_chat_completions_external_route_rewrites_model_and_bypasses_accounts(async_client, monkeypatch):
    _configure_external_route(monkeypatch)
    calls: list[dict[str, JsonValue]] = []

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def post_json(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            session=None,
        ) -> dict[str, JsonValue]:
            del inbound_headers, session
            calls.append({"endpoint_path": endpoint_path, "payload": dict(payload)})
            return {
                "id": "chatcmpl_external",
                "object": "chat.completion",
                "created": 1,
                "model": "minimax/minimax-m3",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "prompt_tokens_details": {"cached_tokens": 1},
                },
            }

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gpt-5.3-codex"
    assert len(calls) == 1
    assert calls[0]["endpoint_path"] == "/chat/completions"
    provider_payload = cast(Mapping[str, JsonValue], calls[0]["payload"])
    assert provider_payload["model"] == "minimax/minimax-m3"
    assert provider_payload["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_v1_chat_completions_external_provider_error_is_returned(async_client, monkeypatch):
    _configure_external_route(monkeypatch)

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def post_json(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            session=None,
        ) -> dict[str, JsonValue]:
            del endpoint_path, payload, inbound_headers, session
            raise ExternalProviderError(
                429,
                openai_error("rate_limit_exceeded", "provider limited", error_type="rate_limit_error"),
                provider_id="openrouter",
                upstream_error_code="rate_limit_exceeded",
            )

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_external_route_uses_public_model_for_api_key_allowlist(async_client, monkeypatch):
    _configure_external_route(monkeypatch)
    await _enable_api_key_auth(async_client)
    created = await async_client.post(
        "/api/api-keys/",
        json={"name": "target-only", "allowedModels": ["minimax/minimax-m3"]},
    )
    assert created.status_code == 200
    key = created.json()["key"]

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def post_json(self, *_args, **_kwargs) -> dict[str, JsonValue]:
            raise AssertionError("provider target model must not satisfy public model allowlist")

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"


@pytest.mark.asyncio
async def test_external_route_uses_enforced_public_model(async_client, monkeypatch):
    _configure_external_route(monkeypatch)
    await _enable_api_key_auth(async_client)
    created = await async_client.post(
        "/api/api-keys/",
        json={"name": "enforced-public", "enforcedModel": "gpt-5.3-codex"},
    )
    assert created.status_code == 200
    key = created.json()["key"]
    calls: list[dict[str, JsonValue]] = []

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def post_json(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            session=None,
        ) -> dict[str, JsonValue]:
            del inbound_headers, session
            calls.append({"endpoint_path": endpoint_path, "payload": dict(payload)})
            return {
                "id": "chatcmpl_external",
                "object": "chat.completion",
                "created": 1,
                "model": "minimax/minimax-m3",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    response = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "gpt-5.2", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5.3-codex"
    provider_payload = cast(Mapping[str, JsonValue], calls[0]["payload"])
    assert provider_payload["model"] == "minimax/minimax-m3"


@pytest.mark.asyncio
async def test_v1_chat_completions_external_stream_rewrites_chunks(async_client, monkeypatch):
    _configure_external_route(monkeypatch)

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def stream_sse(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            max_event_bytes: int,
            session=None,
        ):
            del endpoint_path, payload, inbound_headers, max_event_bytes, session
            yield (
                'data: {"id":"chunk_1","object":"chat.completion.chunk","model":"minimax/minimax-m3","choices":[]}\n\n'
            )
            yield (
                'data: {"id":"chunk_1","object":"chat.completion.chunk",'
                '"model":"minimax/minimax-m3","choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2}}\n\n'
            )
            yield "data: [DONE]\n\n"

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    async with async_client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = "\n".join([line async for line in response.aiter_lines()])

    assert "minimax/minimax-m3" not in body
    assert "gpt-5.3-codex" in body
    assert "[DONE]" in body


@pytest.mark.asyncio
async def test_v1_responses_external_route_rewrites_non_stream_response(async_client, monkeypatch):
    _configure_external_route(monkeypatch, endpoints=["responses"])
    calls: list[dict[str, JsonValue]] = []

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def post_json(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            session=None,
        ) -> dict[str, JsonValue]:
            del inbound_headers, session
            calls.append({"endpoint_path": endpoint_path, "payload": dict(payload)})
            return {
                "id": "resp_external",
                "object": "response",
                "model": "minimax/minimax-m3",
                "status": "completed",
                "output": [],
                "usage": {"input_tokens": 5, "output_tokens": 6},
            }

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    response = await async_client.post(
        "/v1/responses",
        json={"model": "gpt-5.3-codex", "input": [{"role": "user", "content": "hi"}], "stream": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gpt-5.3-codex"
    assert calls[0]["endpoint_path"] == "/responses"
    provider_payload = cast(Mapping[str, JsonValue], calls[0]["payload"])
    assert provider_payload["model"] == "minimax/minimax-m3"
    assert provider_payload["stream"] is False


@pytest.mark.asyncio
async def test_v1_responses_external_route_rewrites_stream_response(async_client, monkeypatch):
    _configure_external_route(monkeypatch, endpoints=["responses"])

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def stream_sse(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            max_event_bytes: int,
            session=None,
        ):
            del endpoint_path, payload, inbound_headers, max_event_bytes, session
            yield (
                'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_external",'
                '"model":"minimax/minimax-m3"}}\n\n'
            )
            yield 'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"hi"}\n\n'
            yield (
                'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_external",'
                '"model":"minimax/minimax-m3","usage":{"input_tokens":5,"output_tokens":6}}}\n\n'
            )

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    async with async_client.stream(
        "POST",
        "/v1/responses",
        json={"model": "gpt-5.3-codex", "input": [{"role": "user", "content": "hi"}], "stream": True},
    ) as response:
        assert response.status_code == 200
        body = "\n".join([line async for line in response.aiter_lines()])

    assert "minimax/minimax-m3" not in body
    assert "gpt-5.3-codex" in body
    assert "response.completed" in body


@pytest.mark.asyncio
async def test_backend_codex_responses_computer_use_context_bridges_mcp_tools(async_client, monkeypatch):
    _configure_external_route(monkeypatch, endpoints=["backend.responses"])
    calls: list[dict[str, JsonValue]] = []

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def stream_sse(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            max_event_bytes: int,
            session=None,
        ):
            del inbound_headers, max_event_bytes, session
            calls.append({"endpoint_path": endpoint_path, "payload": dict(payload)})
            yield (
                "event: response.output_item.done\n"
                'data: {"type":"response.output_item.done","output_index":0,'
                '"item":{"type":"function_call","name":"mcp__computer_use__get_app_state",'
                '"call_id":"call_cua_1","arguments":"{\\"app\\":\\"Dia\\"}"}}\n\n'
            )
            yield (
                "event: response.completed\n"
                'data: {"type":"response.completed","response":{"id":"resp_cua","object":"response",'
                '"status":"completed","model":"minimax/minimax-m3","output":[],'
                '"usage":{"input_tokens":5,"output_tokens":1}}}\n\n'
            )

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    async with async_client.stream(
        "POST",
        "/backend-api/codex/responses",
        json={
            "model": "gpt-5.3-codex",
            "instructions": "base",
            "input": [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Capabilities from the `Computer Use` plugin:\n"
                                "- MCP servers from this plugin available in this session: `computer-use`."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "[@Dia](plugin://computer-use@openai-bundled) open Gemini",
                        }
                    ],
                },
            ],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        body = "\n".join([line async for line in response.aiter_lines()])

    assert len(calls) == 1
    provider_payload = cast(Mapping[str, JsonValue], calls[0]["payload"])
    assert calls[0]["endpoint_path"] == "/responses"
    tools = provider_payload["tools"]
    assert isinstance(tools, list)
    tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    assert "mcp__computer_use__get_app_state" in tool_names
    assert "mcp__computer_use__type_text" in tool_names
    assert "list_mcp_resources" in str(provider_payload["instructions"])

    assert "mcp__computer_use__get_app_state" not in body
    assert '"namespace":"mcp__computer_use"' in body
    assert '"name":"get_app_state"' in body
    assert "minimax/minimax-m3" not in body
    assert "gpt-5.3-codex" in body


@pytest.mark.asyncio
async def test_backend_codex_responses_computer_use_rewrites_resource_listing_attempt(async_client, monkeypatch):
    _configure_external_route(monkeypatch, endpoints=["backend.responses"])

    class FakeProviderClient:
        def __init__(self, provider):
            self.provider = provider

        async def stream_sse(
            self,
            endpoint_path: str,
            payload: Mapping[str, JsonValue],
            inbound_headers: Mapping[str, str],
            *,
            max_event_bytes: int,
            session=None,
        ):
            del endpoint_path, payload, inbound_headers, max_event_bytes, session
            yield (
                "event: response.output_item.done\n"
                'data: {"type":"response.output_item.done","output_index":0,'
                '"item":{"type":"function_call","name":"list_mcp_resources",'
                '"call_id":"call_cua_2","arguments":"{\\"server\\":\\"computer-use\\"}"}}\n\n'
            )
            yield (
                "event: response.completed\n"
                'data: {"type":"response.completed","response":{"id":"resp_cua","object":"response",'
                '"status":"completed","model":"minimax/minimax-m3","output":[]}}\n\n'
            )

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    async with async_client.stream(
        "POST",
        "/backend-api/codex/responses",
        json={
            "model": "gpt-5.3-codex",
            "instructions": "base",
            "input": [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Capabilities from the `Computer Use` plugin: computer-use",
                        }
                    ],
                }
            ],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        body = "\n".join([line async for line in response.aiter_lines()])

    assert "list_mcp_resources" not in body
    assert '"namespace":"mcp__computer_use"' in body
    assert '"name":"list_apps"' in body
    assert '"arguments":"{}"' in body


@pytest.mark.asyncio
async def test_external_route_does_not_merge_provider_models_into_catalog(async_client, monkeypatch):
    _configure_external_route(monkeypatch)

    response = await async_client.get("/v1/models")

    assert response.status_code == 200
    model_ids = {item["id"] for item in response.json()["data"]}
    assert "minimax/minimax-m3" not in model_ids


@pytest.mark.asyncio
async def test_external_route_unsupported_responses_endpoint_returns_public_error(async_client, monkeypatch):
    _configure_external_route(monkeypatch, endpoints=["chat.completions"])

    response = await async_client.post("/v1/responses", json={"model": "gpt-5.3-codex", "input": []})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "external_route_endpoint_unsupported"


@pytest.mark.asyncio
async def test_external_route_unsupported_compact_endpoint_returns_public_error(async_client, monkeypatch):
    _configure_external_route(monkeypatch, endpoints=["chat.completions"])

    response = await async_client.post("/v1/responses/compact", json={"model": "gpt-5.3-codex", "input": []})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "external_route_endpoint_unsupported"


@pytest.mark.asyncio
async def test_backend_codex_responses_requires_backend_external_endpoint(async_client, monkeypatch):
    _configure_external_route(monkeypatch, endpoints=["responses"])

    response = await async_client.post("/backend-api/codex/responses", json={"model": "gpt-5.3-codex", "input": []})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "external_route_endpoint_unsupported"
