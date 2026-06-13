from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_list, is_json_mapping

_HIDDEN_PROVIDER_KEYS = frozenset({"provider"})


def rewrite_public_model_in_payload(
    payload: Mapping[str, JsonValue], *, target_model: str, public_model: str
) -> dict[str, JsonValue]:
    rewritten = _rewrite_value(deepcopy(dict(payload)), target_model=target_model, public_model=public_model)
    return cast(dict[str, JsonValue], rewritten) if is_json_mapping(rewritten) else dict(payload)


def rewrite_public_model_in_sse(event_block: str, *, target_model: str, public_model: str) -> str:
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
    rewritten_payload = rewrite_public_model_in_payload(payload, target_model=target_model, public_model=public_model)
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


def _rewrite_value(
    value: JsonValue,
    *,
    target_model: str,
    public_model: str,
    current_key: str | None = None,
) -> JsonValue:
    if isinstance(value, str) and _is_model_key(current_key) and _matches_provider_model(value, target_model):
        return public_model
    if is_json_mapping(value):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            string_key = str(key)
            if string_key.lower() in _HIDDEN_PROVIDER_KEYS:
                continue
            result[string_key] = _rewrite_value(
                item,
                target_model=target_model,
                public_model=public_model,
                current_key=string_key,
            )
        return result
    if is_json_list(value):
        return [
            _rewrite_value(item, target_model=target_model, public_model=public_model, current_key=current_key)
            for item in value
        ]
    return value


def _is_model_key(key: str | None) -> bool:
    if key is None:
        return False
    normalized = key.replace("-", "_")
    snake = "".join(f"_{char.lower()}" if char.isupper() else char for char in normalized).strip("_")
    return snake == "model" or snake.endswith("_model") or snake in {"models", "model_id"}


def _matches_provider_model(value: str, target_model: str) -> bool:
    return value == target_model or value.startswith(f"{target_model}-")
