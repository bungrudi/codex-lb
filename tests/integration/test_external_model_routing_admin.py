from __future__ import annotations

from collections.abc import Mapping

import pytest
from sqlalchemy import select

import app.modules.proxy.api as proxy_api
from app.core.config.settings import get_settings
from app.core.external_providers.runtime_config import get_external_routing_config_cache
from app.core.types import JsonValue
from app.db.models import ExternalModelRoute, ExternalProvider
from app.db.session import get_background_session

pytestmark = pytest.mark.integration


async def _create_dashboard_provider_and_route(async_client, *, target_model: str = "minimax/minimax-m3") -> str:
    provider = await async_client.post(
        "/api/settings/external-model-routing/providers",
        json={
            "id": "openrouter",
            "baseUrl": "https://openrouter.ai/api/v1",
            "apiKey": "test-dashboard-secret",
            "defaultHeaders": {"HTTP-Referer": "https://codex-lb.local"},
        },
    )
    assert provider.status_code == 200
    provider_payload = provider.json()
    assert provider_payload["id"] == "openrouter"
    assert provider_payload["apiKeyConfigured"] is True
    assert provider_payload["apiKeySource"] == "dashboard"
    assert "apiKey" not in provider_payload

    route = await async_client.post(
        "/api/settings/external-model-routing/routes",
        json={
            "name": "Minimax Codex",
            "publicModel": "gpt-5.3-codex",
            "providerId": "openrouter",
            "targetModel": target_model,
            "endpoints": ["chat.completions"],
        },
    )
    assert route.status_code == 200
    route_payload = route.json()
    assert route_payload["id"]
    assert route_payload["name"] == "Minimax Codex"
    assert route_payload["publicModel"] == "gpt-5.3-codex"
    assert route_payload["targetModel"] == target_model
    assert route_payload["status"] == "active"
    return str(route_payload["id"])


@pytest.mark.asyncio
async def test_external_model_routing_admin_crud_redacts_provider_secret(async_client):
    route_id = await _create_dashboard_provider_and_route(async_client)

    async with get_background_session() as session:
        encrypted = (
            await session.execute(select(ExternalProvider.api_key_encrypted).where(ExternalProvider.id == "openrouter"))
        ).scalar_one()
    assert encrypted is not None
    assert b"test-dashboard-secret" not in encrypted

    admin = await async_client.get("/api/settings/external-model-routing")
    assert admin.status_code == 200
    payload = admin.json()
    assert payload["providers"][0]["apiKeyConfigured"] is True
    assert payload["providers"][0]["apiKeySource"] == "dashboard"
    assert "test-dashboard-secret" not in admin.text
    assert payload["routes"][0]["status"] == "active"

    updated = await async_client.put(
        "/api/settings/external-model-routing/providers/openrouter",
        json={"clearApiKey": True},
    )
    assert updated.status_code == 200
    assert updated.json()["apiKeyConfigured"] is False
    assert updated.json()["apiKeySource"] == "missing"

    deleted_route = await async_client.delete(f"/api/settings/external-model-routing/routes/{route_id}")
    assert deleted_route.status_code == 204
    deleted_provider = await async_client.delete("/api/settings/external-model-routing/providers/openrouter")
    assert deleted_provider.status_code == 204


@pytest.mark.asyncio
async def test_dashboard_managed_route_drives_proxy_without_restart(async_client, monkeypatch):
    await _create_dashboard_provider_and_route(async_client)
    calls: list[dict[str, JsonValue]] = []

    class FakeProviderClient:
        def __init__(self, provider):
            assert provider.id == "openrouter"
            assert provider.api_key == "test-dashboard-secret"
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
                "id": "chatcmpl_dashboard_external",
                "object": "chat.completion",
                "created": 1,
                "model": "minimax/minimax-m3",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "dashboard route ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            }

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5.3-codex"
    assert len(calls) == 1
    assert calls[0]["endpoint_path"] == "/chat/completions"
    assert calls[0]["payload"]["model"] == "minimax/minimax-m3"
    assert calls[0]["payload"]["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_activating_route_profile_deactivates_conflicting_profile(async_client):
    first_route_id = await _create_dashboard_provider_and_route(async_client)
    second = await async_client.post(
        "/api/settings/external-model-routing/routes",
        json={
            "name": "DeepSeek V4 Pro",
            "publicModel": "gpt-5.3-codex",
            "providerId": "openrouter",
            "targetModel": "deepseek/deepseek-v4-pro",
            "endpoints": ["chat.completions"],
            "isActive": False,
        },
    )
    assert second.status_code == 200
    second_route_id = second.json()["id"]

    activated = await async_client.put(
        f"/api/settings/external-model-routing/routes/{second_route_id}",
        json={"isActive": True, "deactivateConflicts": True},
    )
    assert activated.status_code == 200
    assert activated.json()["isActive"] is True

    admin = await async_client.get("/api/settings/external-model-routing")
    assert admin.status_code == 200
    routes = {route["id"]: route for route in admin.json()["routes"]}
    assert routes[first_route_id]["isActive"] is False
    assert routes[second_route_id]["isActive"] is True

    third = await async_client.post(
        "/api/settings/external-model-routing/routes",
        json={
            "name": "Minimax Backend",
            "publicModel": "gpt-5.3-codex",
            "providerId": "openrouter",
            "targetModel": "minimax/minimax-m3",
            "endpoints": ["backend.responses"],
            "isActive": True,
        },
    )
    assert third.status_code == 200
    admin = await async_client.get("/api/settings/external-model-routing")
    routes = {route["id"]: route for route in admin.json()["routes"]}
    assert routes[second_route_id]["isActive"] is True
    assert routes[third.json()["id"]]["isActive"] is True


@pytest.mark.asyncio
async def test_persisted_route_conflict_is_reported_and_fails_closed(async_client):
    first_route_id = await _create_dashboard_provider_and_route(async_client)
    async with get_background_session() as session:
        session.add(
            ExternalModelRoute(
                name="Conflicting profile",
                public_model="gpt-5.3-codex",
                provider_id="openrouter",
                target_model="other/model",
                endpoints_json='["chat.completions"]',
                is_active=True,
            )
        )
        await session.commit()
    await get_external_routing_config_cache().invalidate()

    admin = await async_client.get("/api/settings/external-model-routing")
    assert admin.status_code == 200
    routes = {route["id"]: route for route in admin.json()["routes"]}
    assert routes[first_route_id]["status"] == "conflict"
    assert any(route["status"] == "conflict" for route in routes.values())

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "external_route_conflict"


@pytest.mark.asyncio
async def test_dashboard_route_overrides_env_route(async_client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-env")
    monkeypatch.setenv(
        "CODEX_LB_EXTERNAL_PROVIDERS_JSON",
        '{"openrouter":{"base_url":"https://openrouter.ai/api/v1","api_key_env":"OPENROUTER_API_KEY"}}',
    )
    monkeypatch.setenv(
        "CODEX_LB_EXTERNAL_MODEL_ROUTES_JSON",
        '{"gpt-5.3-codex":{"provider_id":"openrouter","target_model":"env/model","endpoints":["chat.completions"]}}',
    )
    get_settings.cache_clear()
    await _create_dashboard_provider_and_route(async_client, target_model="dashboard/model")
    calls: list[dict[str, JsonValue]] = []

    class FakeProviderClient:
        def __init__(self, provider):
            assert provider.api_key == "test-dashboard-secret"

        async def post_json(self, endpoint_path, payload, inbound_headers, *, session=None):
            del endpoint_path, inbound_headers, session
            calls.append(dict(payload))
            return {
                "id": "chatcmpl_dashboard_override",
                "object": "chat.completion",
                "created": 1,
                "model": "dashboard/model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    monkeypatch.setattr(proxy_api, "OpenAICompatibleProviderClient", FakeProviderClient)

    response = await async_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.3-codex", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert calls[0]["model"] == "dashboard/model"
