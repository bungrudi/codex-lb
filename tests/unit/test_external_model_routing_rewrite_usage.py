from __future__ import annotations

from app.core.external_providers.response_rewrite import rewrite_public_model_in_payload, rewrite_public_model_in_sse
from app.core.external_providers.usage import extract_external_provider_usage


def test_rewrite_public_model_in_payload_replaces_exact_target_model_strings() -> None:
    rewritten = rewrite_public_model_in_payload(
        {
            "model": "minimax/minimax-m3-20260531",
            "choices": [
                {
                    "message": {
                        "model": "minimax/minimax-m3",
                        "content": "provider text may mention minimax/minimax-m3",
                    }
                }
            ],
            "provider_model": "minimax/minimax-m3",
            "provider": "Minimax",
        },
        target_model="minimax/minimax-m3",
        public_model="gpt-5.3-codex",
    )

    assert rewritten["model"] == "gpt-5.3-codex"
    assert rewritten["choices"] == [
        {"message": {"model": "gpt-5.3-codex", "content": "provider text may mention minimax/minimax-m3"}}
    ]
    assert rewritten["provider_model"] == "gpt-5.3-codex"
    assert "provider" not in rewritten


def test_rewrite_public_model_in_sse_preserves_event_and_done_frames() -> None:
    rewritten = rewrite_public_model_in_sse(
        'event: response.created\ndata: {"type":"response.created","response":{"model":"minimax/minimax-m3"}}\n\n',
        target_model="minimax/minimax-m3",
        public_model="gpt-5.3-codex",
    )

    assert "event: response.created" in rewritten
    assert '"model":"gpt-5.3-codex"' in rewritten
    assert (
        rewrite_public_model_in_sse(
            "data: [DONE]\n\n",
            target_model="minimax/minimax-m3",
            public_model="gpt-5.3-codex",
        )
        == "data: [DONE]\n\n"
    )


def test_extract_external_provider_usage_supports_chat_and_responses_shapes() -> None:
    chat_usage = extract_external_provider_usage(
        {
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 3},
                "completion_tokens_details": {"reasoning_tokens": 5},
            }
        }
    )
    responses_usage = extract_external_provider_usage(
        {
            "response": {
                "usage": {
                    "input_tokens": 13,
                    "output_tokens": 17,
                    "input_tokens_details": {"cached_tokens": 2},
                    "output_tokens_details": {"reasoning_tokens": 4},
                }
            }
        }
    )

    assert chat_usage is not None
    assert chat_usage.input_tokens == 11
    assert chat_usage.output_tokens == 7
    assert chat_usage.cached_input_tokens == 3
    assert chat_usage.reasoning_tokens == 5
    assert responses_usage is not None
    assert responses_usage.input_tokens == 13
    assert responses_usage.output_tokens == 17
    assert responses_usage.cached_input_tokens == 2
    assert responses_usage.reasoning_tokens == 4
