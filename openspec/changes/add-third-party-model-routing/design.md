# Design: third-party model routing behind public Codex/OpenAI model names

## Background

`codex-lb` currently exposes OpenAI/Codex-compatible endpoints backed by a pool of ChatGPT accounts. Model catalogs come from the ChatGPT/Codex upstream model registry with a static bootstrap fallback. Request routing then selects an eligible account, refreshes account auth when needed, and forwards to ChatGPT/Codex upstream endpoints.

The new route layer adds an opt-in path for OpenAI-compatible third-party providers without changing the public model catalog. A configured public model slug such as `gpt-5.3-codex` can route internally to an OpenRouter target such as `minimax/minimax-m3`, while clients still list and receive `gpt-5.3-codex`.

The original detailed planning notes are in `plan.md`.

## Codebase findings

Graphify was run on `app/` and identified the important integration points:

- `app/modules/proxy/api.py` owns public `/v1/*` and `/backend-api/codex/*` route handling.
- `app/modules/proxy/request_policy.py` normalizes public model aliases and applies API-key model, reasoning, and service-tier policy.
- `app/modules/proxy/_service/streaming/*` and `app/modules/proxy/service.py` own ChatGPT account selection, retries, account health, and request-log settlement.
- `app/core/clients/proxy.py` owns raw ChatGPT/Codex upstream calls.
- `app/core/openai/model_registry.py` and `app/core/clients/model_fetcher.py` own model catalog data.
- `app/core/openai/chat_requests.py`, `app/core/openai/chat_responses.py`, `app/core/openai/requests.py`, and `app/core/openai/models.py` own OpenAI-compatible request and response contracts.

The external route resolver should sit after request validation and public model policy, but before ChatGPT account selection.

## Key decisions

### Public model identity remains authoritative

Use three names internally:

- `public_model`: client-visible model id, e.g. `gpt-5.3-codex`.
- `provider_id`: internal provider id, e.g. `openrouter`.
- `target_model`: provider wire model id, e.g. `minimax/minimax-m3`.

External responses should expose `public_model`; request logs and diagnostics should also store `provider_id` and `target_model` for operators.

### Model catalogs do not merge provider catalogs

`/v1/models` and `/backend-api/codex/models` continue to use the existing model registry and bootstrap fallback. Provider route configuration does not add provider model ids to public catalogs. This keeps clients pinned to normal GPT/Codex names and prevents target model leaks through discovery.

### Exact route matching only

The first implementation uses exact public model plus endpoint matching. There are no wildcard, weighted, or fallback-chain routes. If a configured route does not match the request endpoint, the request fails with a deterministic unsupported-endpoint OpenAI error rather than silently using a different provider or the ChatGPT pool.

### Fallback is off by default

A matching external route owns the request. Provider failure returns a provider-derived OpenAI-compatible error by default. Fallback to the ChatGPT account pool may be added as an explicit per-route setting for retryable failures only, with clear logs and request-log metadata.

### Provider routing is separate from upstream proxy-pool egress

Existing upstream proxy-pool routing selects network egress for ChatGPT account traffic. External model routing selects a model provider. The provider client should live in a separate module to avoid mixing ChatGPT account auth with provider API-key auth.

## Proposed modules

```text
app/core/external_providers/
  __init__.py
  config.py
  resolver.py
  openai_compatible.py
  response_rewrite.py
  usage.py

app/modules/proxy/_service/external.py
```

The exact filenames can change during implementation, but the separation of concerns should remain.

## Configuration shape

Environment/static config is the first target, following existing `CODEX_LB_*` settings patterns:

```bash
OPENROUTER_API_KEY=sk-or-...

CODEX_LB_EXTERNAL_PROVIDERS_JSON='{
  "openrouter": {
    "kind": "openai_compatible",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
    "default_headers": {"X-Title": "codex-lb"},
    "enabled": true
  }
}'

CODEX_LB_EXTERNAL_MODEL_ROUTES_JSON='{
  "gpt-5.3-codex": {
    "provider_id": "openrouter",
    "target_model": "minimax/minimax-m3",
    "endpoints": ["chat.completions", "responses"],
    "preserve_public_model": true,
    "fallback_to_codex_pool": false
  }
}'
```

Provider keys should live in environment variables by default. Dashboard-managed encrypted secrets can be considered later.

## Request flow

1. Parse and validate the request exactly as today.
2. Apply existing public alias normalization and API-key model enforcement.
3. Resolve an external route for `(public_model, endpoint)`.
4. If no route matches, continue existing ChatGPT account-pool behavior.
5. If a route matches, enforce API-key rate limits against the public model, bypass ChatGPT account selection, send the provider request using the target model, rewrite provider response model fields back to the public model, and persist internal provider metadata.

## Endpoint strategy

- `/v1/chat/completions`: first production target because OpenRouter is broadly OpenAI Chat Completions compatible.
- HTTP `/v1/responses`: second target where provider `/responses` support is available; avoid the ChatGPT HTTP bridge for external routes.
- `/backend-api/codex/responses`: opt-in only because Codex-native clients may expect Codex-specific events and continuity behavior.
- `/responses/compact` and websockets: unsupported by default until a compact/websocket strategy is explicitly implemented.
- Images/audio/future endpoints: route only when the endpoint is explicitly declared in route config.

## Usage and request logs

API-key allowlists, enforced models, and model-scoped limits use `public_model`. Provider token usage should be converted into existing usage fields where possible. If usage is absent, reservations must still be finalized or released exactly once.

Request logs should keep `model = public_model` and `account_id = NULL` for provider-routed requests, with additional provider metadata columns or equivalent structured metadata for `provider_id`, `target_model`, endpoint, fallback status, and fallback reason.

## Dashboard-managed routing config

The operator-selected GUI scope is hybrid full GUI management inside the existing Settings page. The dashboard should manage provider records, encrypted provider API keys, and exact public-model route records; it should not create a separate standalone model-mapping GUI.

Use normalized tables rather than adding large JSON blobs to `dashboard_settings` because operators need CRUD operations, secret metadata, route status, and future health/test actions:

- `external_providers`: provider id, kind, base URL, encrypted API key, optional API-key env fallback, non-secret default headers JSON, timeouts, enabled flag, insecure-local override, timestamps.
- `external_model_routes`: route profile id, display name, public model, provider id, target model, endpoints JSON, request overrides JSON, stripped request fields JSON, preserve-public-model flag, fallback flag, pricing JSON, enabled flag, timestamps.

Keep environment config supported as bootstrap/static config. At runtime, build an effective config by merging env config with dashboard-managed rows. Dashboard provider rows take precedence for the same provider id. Active dashboard route profiles take precedence over env routes for the same public model and endpoint, and dashboard writes invalidate a short-lived effective-config cache so route changes work without process restart.

Route profiles are intentionally modeled as multiple saved rows per public model. Operators can keep `gpt-5.3-codex -> Minimax` and `gpt-5.3-codex -> DeepSeek` profiles side by side, then switch by activation. The service enforces at most one active dashboard profile for a given `(public_model, endpoint)` by deactivating overlapping active profiles when a profile is activated. Disjoint endpoint profiles for the same public model may remain active simultaneously.

Provider secrets should use the existing `TokenEncryptor` pattern. Admin responses expose `api_key_configured` / `api_key_source` metadata only. Create/update requests may include a new secret; omission preserves the prior secret; an explicit clear operation removes it. The provider client can already accept an explicit API key, so the resolver/effective config layer can pass a decrypted dashboard key without placing raw secrets in public schemas.

Frontend work belongs as a Settings section/submenu near existing routing and upstream proxy controls. The UI should show:

- provider list/form: id, base URL, enabled flag, API-key configured badge, API-key update field, optional headers/timeouts advanced controls;
- route-profile list/form: profile name, public model, provider select, target model, endpoint checkboxes, enabled flag, advanced request overrides/strip fields;
- warnings that external routes send prompts/tool context to the configured third-party provider;
- route health/status hints such as missing key, provider disabled, endpoint unsupported, or activation conflict.
- active map summary grouped by public model and endpoint so the operator can see what is live now.

## Security and privacy

- External routing is opt-in and disabled when no config exists.
- Provider base URLs should be HTTPS unless an explicit local-test escape hatch is enabled.
- Provider credentials and credential-bearing custom headers must be redacted in logs, dashboard responses, and archives.
- Client-facing responses and model lists must not expose provider ids or target model ids.
- Operator logs and authenticated dashboard-admin views may reveal actual provider routing to avoid misleading diagnostics.

## Open questions for implementation

- Whether account-assigned API keys should be allowed to use provider routes by default or require a future provider-assignment scope.
- Which compact strategy should be supported first: unsupported, ChatGPT-pool compact, provider pass-through, or synthetic compact.
- Whether any provider supports a compatible websocket contract that is safe for Codex-native clients.
