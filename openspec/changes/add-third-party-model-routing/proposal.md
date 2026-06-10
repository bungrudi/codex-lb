## Why

Operators want to pool ChatGPT/Codex subscriptions while selectively routing some public GPT/Codex model names to third-party OpenAI-compatible providers such as OpenRouter. Today model selection is tied to the ChatGPT account pool, so using a provider model requires exposing that provider/model id to clients or bypassing `codex-lb`.

## What Changes

- Add opt-in external provider configuration and exact public-model route mappings, e.g. `gpt-5.3-codex -> openrouter:minimax/minimax-m3`.
- Add dashboard Settings management for providers, encrypted provider API keys, and exact public-model route mappings.
- Preserve the normal public model catalogs on `/v1/models` and `/backend-api/codex/models`; provider ids and target model ids stay hidden from clients.
- Route configured endpoint requests to an OpenAI-compatible provider before ChatGPT account selection while preserving OpenAI-compatible response shapes and public model ids.
- Keep unmatched models on the existing ChatGPT account-pool path.
- Enforce API-key model policy, rate limits, usage settlement, and request logging against the public model, while recording internal provider metadata for operators.
- Fail deterministically when a route matches but the provider is unavailable or the requested endpoint is not enabled for that route; ChatGPT fallback remains disabled unless explicitly configured.

## Impact

- Affected specs: `external-model-routing` (new), `model-catalog-compat`, `chat-completions-compat`, `responses-api-compat`, `api-keys`, `proxy-runtime-observability`
- Affected code: `app/core/config/settings.py`, new provider routing/client modules, `app/modules/proxy/api.py`, `app/modules/proxy/request_policy.py`, `app/modules/proxy/service.py`, request-log models/repositories/migrations, settings/dashboard provider-route management surfaces, and proxy compatibility tests
