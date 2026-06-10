from __future__ import annotations

from dataclasses import dataclass

from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_mapping


@dataclass(frozen=True, slots=True)
class ExternalProviderUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int | None = None

    @property
    def has_billable_tokens(self) -> bool:
        return self.input_tokens > 0 or self.output_tokens > 0


def extract_external_provider_usage(payload: JsonValue) -> ExternalProviderUsage | None:
    if not is_json_mapping(payload):
        return None
    usage = payload.get("usage")
    if not is_json_mapping(usage):
        response = payload.get("response")
        if is_json_mapping(response):
            usage = response.get("usage")
    if not is_json_mapping(usage):
        return None

    input_tokens = _int_value(usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _int_value(usage.get("prompt_tokens"))
    output_tokens = _int_value(usage.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _int_value(usage.get("completion_tokens"))
    if input_tokens is None and output_tokens is None:
        return None

    cached_input_tokens = _cached_tokens(usage)
    reasoning_tokens = _reasoning_tokens(usage)
    return ExternalProviderUsage(
        input_tokens=max(0, input_tokens or 0),
        output_tokens=max(0, output_tokens or 0),
        cached_input_tokens=max(0, min(cached_input_tokens or 0, input_tokens or 0)),
        reasoning_tokens=reasoning_tokens,
    )


def _cached_tokens(usage: dict[str, JsonValue]) -> int | None:
    prompt_details = usage.get("prompt_tokens_details")
    if is_json_mapping(prompt_details):
        value = _int_value(prompt_details.get("cached_tokens"))
        if value is not None:
            return value
    input_details = usage.get("input_tokens_details")
    if is_json_mapping(input_details):
        value = _int_value(input_details.get("cached_tokens"))
        if value is not None:
            return value
    return None


def _reasoning_tokens(usage: dict[str, JsonValue]) -> int | None:
    completion_details = usage.get("completion_tokens_details")
    if is_json_mapping(completion_details):
        value = _int_value(completion_details.get("reasoning_tokens"))
        if value is not None:
            return value
    output_details = usage.get("output_tokens_details")
    if is_json_mapping(output_details):
        value = _int_value(output_details.get("reasoning_tokens"))
        if value is not None:
            return value
    return None


def _int_value(value: JsonValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
