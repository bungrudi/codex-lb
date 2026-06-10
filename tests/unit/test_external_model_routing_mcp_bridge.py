from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from app.core.external_providers.mcp_bridge import (
    COMPUTER_USE_MCP_NAMESPACE,
    bridge_computer_use_mcp_provider_request,
    rewrite_computer_use_mcp_response_payload,
    rewrite_computer_use_mcp_response_sse,
    should_bridge_computer_use_mcp,
)
from app.core.types import JsonValue


def _computer_use_payload() -> dict[str, JsonValue]:
    return {
        "model": "minimax/minimax-m3",
        "instructions": "base instructions",
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
                "type": "function_call",
                "namespace": COMPUTER_USE_MCP_NAMESPACE,
                "name": "get_app_state",
                "call_id": "call_1",
                "arguments": '{"app":"Dia"}',
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "[]"},
        ],
        "tools": [{"type": "function", "name": "existing", "parameters": {"type": "object"}}],
    }


def test_should_bridge_computer_use_mcp_detects_plugin_context() -> None:
    assert should_bridge_computer_use_mcp(_computer_use_payload()) is True
    assert should_bridge_computer_use_mcp({"instructions": "ordinary", "input": []}) is False


def test_bridge_provider_request_adds_tools_and_rewrites_prior_namespace_calls() -> None:
    bridged = bridge_computer_use_mcp_provider_request(_computer_use_payload())

    tools = cast(list[JsonValue], bridged["tools"])
    tool_names = {
        cast(Mapping[str, JsonValue], tool).get("name")
        for tool in tools
        if isinstance(tool, Mapping)
    }
    assert "existing" in tool_names
    assert "mcp__computer_use__list_apps" in tool_names
    assert "mcp__computer_use__get_app_state" in tool_names
    assert "mcp__computer_use__type_text" in tool_names
    instructions = cast(str, bridged["instructions"])
    assert "list_mcp_resources" in instructions
    assert "Before every UI action" in instructions
    assert "same\nmodel response" in instructions
    assert "with no assistant text between" in instructions
    assert "Do not switch to shell commands" in instructions

    input_items = cast(list[JsonValue], bridged["input"])
    previous_call = cast(Mapping[str, JsonValue], input_items[1])
    assert previous_call["name"] == "mcp__computer_use__get_app_state"
    assert "namespace" not in previous_call


def test_rewrite_response_payload_converts_synthetic_tool_call_to_codex_namespace() -> None:
    rewritten = rewrite_computer_use_mcp_response_payload(
        {
            "type": "response.output_item.done",
            "response": {
                "instructions": (
                    "base\n\n<codex-lb-external-provider-computer-use-compat>\n"
                    "internal bridge note\n"
                    "</codex-lb-external-provider-computer-use-compat>"
                )
            },
            "item": {
                "type": "function_call",
                "name": "mcp__computer_use__get_app_state",
                "call_id": "call_2",
                "arguments": '{"app":"Dia"}',
            },
        }
    )

    response = cast(Mapping[str, JsonValue], rewritten["response"])
    item = cast(Mapping[str, JsonValue], rewritten["item"])
    assert response["instructions"] == "base"
    assert item["namespace"] == COMPUTER_USE_MCP_NAMESPACE
    assert item["name"] == "get_app_state"
    assert item["call_id"] == "call_2"
    assert item["arguments"] == '{"app":"Dia"}'


def test_rewrite_response_payload_maps_bad_resource_listing_attempt_to_list_apps() -> None:
    rewritten = rewrite_computer_use_mcp_response_payload(
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": "list_mcp_resources",
                "call_id": "call_3",
                "arguments": json.dumps({"server": "computer-use"}),
            },
        }
    )

    item = cast(Mapping[str, JsonValue], rewritten["item"])
    assert item["namespace"] == COMPUTER_USE_MCP_NAMESPACE
    assert item["name"] == "list_apps"
    assert item["arguments"] == "{}"


def test_rewrite_response_sse_converts_synthetic_tool_call_to_codex_namespace() -> None:
    event = (
        'event: response.output_item.done\n'
        'data: {"type":"response.output_item.done","item":{"type":"function_call",'
        '"name":"mcp__computer_use__type_text","call_id":"call_4",'
        '"arguments":"{\\"app\\":\\"Dia\\",\\"text\\":\\"hi\\"}"}}\n\n'
    )

    rewritten = rewrite_computer_use_mcp_response_sse(event)

    assert "event: response.output_item.done" in rewritten
    assert "mcp__computer_use__type_text" not in rewritten
    assert '"namespace":"mcp__computer_use"' in rewritten
    assert '"name":"type_text"' in rewritten
