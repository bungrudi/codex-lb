from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping

COMPUTER_USE_MCP_NAMESPACE = "mcp__computer_use"
COMPUTER_USE_SYNTHETIC_PREFIX = f"{COMPUTER_USE_MCP_NAMESPACE}__"

_COMPUTER_USE_PLUGIN_MARKERS = (
    "plugin://computer-use@openai-bundled",
    "computer-use@openai-bundled",
    "Capabilities from the `Computer Use` plugin",
    "MCP servers from this plugin available in this session: `computer-use`",
)
_COMPUTER_USE_SERVER_ID = "computer-use"

_COMPUTER_USE_TOOL_DEFINITIONS: tuple[dict[str, JsonValue], ...] = (
    {
        "name": "list_apps",
        "description": (
            "List the apps on this computer. Returns running apps and apps used recently, including usage details."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_app_state",
        "description": (
            "Start an app use session if needed, then get the state of the app's key window and return "
            "a screenshot and accessibility tree. Call this once per assistant turn before interacting with the app."
        ),
        "parameters": {
            "type": "object",
            "properties": {"app": {"type": "string", "description": "App name, full app path, or bundle id"}},
            "required": ["app"],
            "additionalProperties": False,
        },
    },
    {
        "name": "click",
        "description": "Click an element by index or pixel coordinates from the screenshot.",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name, full app path, or bundle id"},
                "element_index": {"type": "string", "description": "Element index to click"},
                "x": {"type": "number", "description": "X coordinate in screenshot pixel coordinates"},
                "y": {"type": "number", "description": "Y coordinate in screenshot pixel coordinates"},
                "mouse_button": {"type": "string", "enum": ["left", "right", "middle"]},
                "click_count": {"type": "integer", "description": "Number of clicks. Defaults to 1"},
            },
            "required": ["app"],
            "additionalProperties": False,
        },
    },
    {
        "name": "perform_secondary_action",
        "description": "Invoke a secondary accessibility action exposed by an element.",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name, full app path, or bundle id"},
                "element_index": {"type": "string", "description": "Element identifier"},
                "action": {"type": "string", "description": "Secondary accessibility action name"},
            },
            "required": ["app", "element_index", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_value",
        "description": "Set the value of a settable accessibility element.",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name, full app path, or bundle id"},
                "element_index": {"type": "string", "description": "Element identifier"},
                "value": {"type": "string", "description": "Value to assign"},
            },
            "required": ["app", "element_index", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "select_text",
        "description": (
            "Select text inside a text element, or place the text cursor before or after it. Provide text exactly "
            "as it appears in the accessibility tree."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name or bundle id"},
                "element_index": {"type": "string", "description": "Text element identifier"},
                "text": {"type": "string", "description": "Target text as shown in the accessibility tree"},
                "prefix": {"type": "string", "description": "Optional text immediately before the target"},
                "suffix": {"type": "string", "description": "Optional text immediately after the target"},
                "selection": {
                    "type": "string",
                    "enum": ["text", "cursor_before", "cursor_after"],
                    "description": "Whether to select text or place the cursor. Defaults to text.",
                },
            },
            "required": ["app", "element_index", "text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "scroll",
        "description": "Scroll an element in a direction by a number of pages.",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name, full app path, or bundle id"},
                "element_index": {"type": "string", "description": "Element identifier"},
                "direction": {"type": "string", "description": "Scroll direction: up, down, left, or right"},
                "pages": {"type": "number", "description": "Number of pages to scroll. Defaults to 1"},
            },
            "required": ["app", "element_index", "direction"],
            "additionalProperties": False,
        },
    },
    {
        "name": "drag",
        "description": "Drag from one point to another using pixel coordinates.",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name, full app path, or bundle id"},
                "from_x": {"type": "number", "description": "Start X coordinate"},
                "from_y": {"type": "number", "description": "Start Y coordinate"},
                "to_x": {"type": "number", "description": "End X coordinate"},
                "to_y": {"type": "number", "description": "End Y coordinate"},
            },
            "required": ["app", "from_x", "from_y", "to_x", "to_y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "press_key",
        "description": ("Press a key or key-combination on the keyboard. Examples: a, Return, Tab, super+c, Up, KP_0."),
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name, full app path, or bundle id"},
                "key": {"type": "string", "description": "Key or key combination to press"},
            },
            "required": ["app", "key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "type_text",
        "description": "Type literal text using keyboard input.",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name, full app path, or bundle id"},
                "text": {"type": "string", "description": "Literal text to type"},
            },
            "required": ["app", "text"],
            "additionalProperties": False,
        },
    },
)
_COMPUTER_USE_TOOL_NAMES = frozenset(cast(str, definition["name"]) for definition in _COMPUTER_USE_TOOL_DEFINITIONS)

_COMPUTER_USE_PROVIDER_INSTRUCTIONS_START = "<codex-lb-external-provider-computer-use-compat>"
_COMPUTER_USE_PROVIDER_INSTRUCTIONS_END = "</codex-lb-external-provider-computer-use-compat>"
_COMPUTER_USE_PROVIDER_INSTRUCTIONS = f"""

{_COMPUTER_USE_PROVIDER_INSTRUCTIONS_START}
Computer Use is available through function tools whose names start with `mcp__computer_use__`.
Use these functions to control the local Mac UI. Do not call `list_mcp_resources`,
`read_mcp_resource`, or `list_mcp_resource_templates` for `computer-use`; that MCP server
exposes tools, not resources. Use `mcp__computer_use__list_apps` to discover apps.
Before every UI action (`click`, `perform_secondary_action`, `set_value`, `select_text`,
`scroll`, `drag`, `press_key`, or `type_text`), refresh the Computer Use state in the same
model response: emit `mcp__computer_use__get_app_state` for the same app immediately followed
by exactly one UI action, with no assistant text between those adjacent function calls. The
state is short-lived and can expire during provider reasoning, so a `get_app_state` call from
a previous provider round trip is not enough. Use the most recently observed element index or
keyboard plan for the paired action; after both tool outputs return, inspect the fresh state
and continue with the next paired state+action step. If an action says Computer Use is not
active, recover by emitting the paired `get_app_state` + intended UI action in the same model
response. Do not switch to shell commands, AppleScript, macOS `open`, or another browser/tool
fallback unless the user explicitly approves that fallback. The proxy will translate these
function calls back to Codex Computer Use MCP calls for the client.
{_COMPUTER_USE_PROVIDER_INSTRUCTIONS_END}"""


def should_bridge_computer_use_mcp(payload: Mapping[str, JsonValue]) -> bool:
    """Return true when a backend Codex Responses payload asks for Computer Use plugin capability."""
    return _payload_contains_computer_use_marker(payload)


def bridge_computer_use_mcp_provider_request(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Expose Codex Computer Use MCP tools as provider-visible function tools.

    Third-party OpenAI-compatible providers generally do not know Codex's `namespace`
    extension on Responses `function_call` items. This bridge gives them plain function
    tool names, then rewrites their calls back to the Codex MCP namespace on the response path.
    """
    bridged = cast(dict[str, JsonValue], _rewrite_client_mcp_calls_for_provider(deepcopy(dict(payload))))
    bridged["tools"] = _provider_tools_with_computer_use(bridged.get("tools"))
    bridged["instructions"] = _instructions_with_computer_use_bridge(bridged.get("instructions"))
    return bridged


def rewrite_computer_use_mcp_response_payload(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Rewrite provider-visible Computer Use function calls into Codex MCP namespace calls."""
    rewritten = _rewrite_provider_mcp_calls_for_client(deepcopy(dict(payload)))
    return cast(dict[str, JsonValue], rewritten) if is_json_mapping(rewritten) else dict(payload)


def rewrite_computer_use_mcp_response_sse(event_block: str) -> str:
    data_lines: list[str] = []
    for line in event_block.splitlines():
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)
    if not data_lines:
        return event_block
    raw_data = "\n".join(data_lines)
    if raw_data.strip() == "[DONE]":
        return event_block
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        return event_block
    if not is_json_mapping(payload):
        return event_block
    rewritten_payload = rewrite_computer_use_mcp_response_payload(payload)
    rewritten_data = json.dumps(rewritten_payload, ensure_ascii=True, separators=(",", ":"))

    output_lines: list[str] = []
    replaced = False
    for line in event_block.splitlines(keepends=True):
        line_body = line[:-1] if line.endswith("\n") else line
        line_end = "\n" if line.endswith("\n") else ""
        if line_body.startswith("data:"):
            if not replaced:
                output_lines.append(f"data: {rewritten_data}{line_end}")
                replaced = True
            continue
        output_lines.append(line)
    if event_block.endswith("\n\n") and (not output_lines or not output_lines[-1].endswith("\n")):
        output_lines.append("\n")
    return "".join(output_lines)


def _payload_contains_computer_use_marker(value: JsonValue) -> bool:
    if isinstance(value, str):
        return any(marker in value for marker in _COMPUTER_USE_PLUGIN_MARKERS)
    if is_json_mapping(value):
        namespace = value.get("namespace")
        if namespace == COMPUTER_USE_MCP_NAMESPACE:
            return True
        for item in value.values():
            if _payload_contains_computer_use_marker(item):
                return True
        return False
    if is_json_list(value):
        return any(_payload_contains_computer_use_marker(item) for item in value)
    return False


def _provider_tools_with_computer_use(value: JsonValue) -> list[JsonValue]:
    tools = list(value) if is_json_list(value) else []
    existing_names = {tool.get("name") for tool in tools if is_json_mapping(tool) and isinstance(tool.get("name"), str)}
    for definition in _COMPUTER_USE_TOOL_DEFINITIONS:
        tool_name = cast(str, definition["name"])
        provider_name = _provider_tool_name(tool_name)
        if provider_name in existing_names:
            continue
        tools.append(
            {
                "type": "function",
                "name": provider_name,
                "description": f"Computer Use MCP tool `{tool_name}`. {definition['description']}",
                "parameters": definition["parameters"],
            }
        )
        existing_names.add(provider_name)
    return tools


def _instructions_with_computer_use_bridge(value: JsonValue) -> str:
    existing = value if isinstance(value, str) else ""
    if _COMPUTER_USE_PROVIDER_INSTRUCTIONS_START in existing:
        return existing
    return f"{existing}{_COMPUTER_USE_PROVIDER_INSTRUCTIONS}"


def _rewrite_client_mcp_calls_for_provider(value: JsonValue) -> JsonValue:
    if is_json_mapping(value):
        result: dict[str, JsonValue] = {}
        namespace = value.get("namespace")
        raw_name = value.get("name")
        for key, item in value.items():
            if key == "namespace" and namespace == COMPUTER_USE_MCP_NAMESPACE:
                continue
            if key == "name" and namespace == COMPUTER_USE_MCP_NAMESPACE and isinstance(raw_name, str):
                result[key] = _provider_tool_name(raw_name)
                continue
            result[key] = _rewrite_client_mcp_calls_for_provider(item)
        return result
    if is_json_list(value):
        return [_rewrite_client_mcp_calls_for_provider(item) for item in value]
    return value


def _rewrite_provider_mcp_calls_for_client(value: JsonValue) -> JsonValue:
    if is_json_mapping(value):
        rewritten_children: dict[str, JsonValue] = {}
        for key, item in value.items():
            string_key = str(key)
            if string_key == "instructions" and isinstance(item, str):
                rewritten_children[string_key] = _strip_computer_use_bridge_instructions(item)
                continue
            rewritten_children[string_key] = _rewrite_provider_mcp_calls_for_client(item)
        return _rewrite_provider_function_call_for_client(rewritten_children)
    if is_json_list(value):
        return [_rewrite_provider_mcp_calls_for_client(item) for item in value]
    return value


def _rewrite_provider_function_call_for_client(item: dict[str, JsonValue]) -> dict[str, JsonValue]:
    raw_name = item.get("name")
    if not isinstance(raw_name, str):
        return item

    tool_name = _computer_use_tool_name_from_provider_name(raw_name)
    if tool_name is not None:
        rewritten = dict(item)
        rewritten["namespace"] = COMPUTER_USE_MCP_NAMESPACE
        rewritten["name"] = tool_name
        return rewritten

    if raw_name == "list_mcp_resources" and _function_call_targets_computer_use_server(item):
        rewritten = dict(item)
        rewritten["namespace"] = COMPUTER_USE_MCP_NAMESPACE
        rewritten["name"] = "list_apps"
        rewritten["arguments"] = "{}"
        return rewritten

    return item


def _provider_tool_name(tool_name: str) -> str:
    return f"{COMPUTER_USE_SYNTHETIC_PREFIX}{tool_name}"


def _strip_computer_use_bridge_instructions(value: str) -> str:
    start = value.find(_COMPUTER_USE_PROVIDER_INSTRUCTIONS_START)
    if start < 0:
        return value
    end = value.find(_COMPUTER_USE_PROVIDER_INSTRUCTIONS_END, start)
    if end < 0:
        return value[:start].rstrip()
    end += len(_COMPUTER_USE_PROVIDER_INSTRUCTIONS_END)
    return f"{value[:start]}{value[end:]}".strip()


def _computer_use_tool_name_from_provider_name(name: str) -> str | None:
    if not name.startswith(COMPUTER_USE_SYNTHETIC_PREFIX):
        return None
    tool_name = name.removeprefix(COMPUTER_USE_SYNTHETIC_PREFIX)
    return tool_name if tool_name in _COMPUTER_USE_TOOL_NAMES else None


def _function_call_targets_computer_use_server(item: Mapping[str, JsonValue]) -> bool:
    raw_arguments = item.get("arguments")
    arguments: Mapping[str, JsonValue] | None = None
    if is_json_mapping(raw_arguments):
        arguments = raw_arguments
    elif isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            parsed = None
        if is_json_mapping(parsed):
            arguments = parsed
    if arguments is None:
        return False
    return arguments.get("server") == _COMPUTER_USE_SERVER_ID
