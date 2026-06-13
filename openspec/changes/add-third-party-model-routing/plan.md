# Plan: hidden third-party model routing behind Codex/OpenAI model names

## Status

Planning document only. It is not a normative OpenSpec spec yet.

This file is intentionally placed under `openspec/changes/` instead of `docs/` because this repo treats OpenSpec as the source of truth for behavior, API, schema, routing, dashboard-visible, and compatibility changes.

## Objective

Add an exact model-route override layer to `codex-lb` so an operator can keep exposing the normal Codex/OpenAI-compatible model catalog while routing selected public model slugs to a third-party OpenAI-compatible provider.

Example target behavior:

```text
Client sees:        GET /v1/models -> gpt-5.3-codex, gpt-5.4, ...
Client sends:       model = "gpt-5.3-codex"
Internal route:     gpt-5.3-codex -> openrouter:minimax/minimax-m3
Provider request:   model = "minimax/minimax-m3"
Client response:    model fields rewritten/preserved as "gpt-5.3-codex"
```

Default behavior must remain unchanged when no exact route is configured.

## Confirmed product requirements

- Pool multiple ChatGPT subscriptions as `codex-lb` already does.
- Add third-party model routing, initially OpenRouter.
- Third-party targets are OpenAI-compatible.
- Externally hide provider/model identity behind normal GPT/Codex model names.
- `/v1/models` and `/backend-api/codex/models` should continue returning the normal GPT/Codex catalog, not OpenRouter/Minimax model ids.
- Routing mode is exact public-model mapping only.
- If no exact route matches, use normal `codex-lb` account-pool routing.
- Support all OpenAI-compatible clients and all endpoints `codex-lb` already supports, phased by endpoint feasibility.

## Graphify/codebase findings

Graphify was run on `codex-lb/app` and produced a backend graph with **6,056 nodes**, **24,454 edges**, and **328 communities**. The relevant communities were:

- **HTTP Bridge Forwarding** and **SSE Transport Layer**: public `/responses` streaming and bridge continuity.
- **Upstream Proxy Logic** and **Codex Transport Client**: calls to ChatGPT/Codex upstream.
- **Proxy Request Models**, **Chat Request Validation**, **Chat Response Parsing**: OpenAI request/response compatibility.
- **Model Registry Validation** and **Upstream Model Fetcher**: model catalog construction.
- **API Key Usage Service**, **Usage Cost Calculation**, **Request Log Service**: rate limiting, billing, and observability.
- **System Configuration Settings** and **Dashboard Settings**: env/runtime configuration patterns.

Important code paths:

| Area | Existing files |
|---|---|
| Public routes | `app/modules/proxy/api.py` |
| Request model aliasing and API-key model policy | `app/modules/proxy/request_policy.py` |
| Account-pool streaming/retry selection | `app/modules/proxy/_service/streaming/retry.py`, `app/modules/proxy/_service/streaming/mixin.py`, `app/modules/proxy/service.py` |
| Raw ChatGPT/Codex upstream calls | `app/core/clients/proxy.py` |
| Model registry/catalog | `app/core/openai/model_registry.py`, `app/core/clients/model_fetcher.py` |
| Chat request/response conversion | `app/core/openai/chat_requests.py`, `app/core/openai/chat_responses.py` |
| Responses request/response models | `app/core/openai/requests.py`, `app/core/openai/models.py`, `app/core/openai/v1_requests.py` |
| Runtime settings | `app/core/config/settings.py`, `app/db/models.py::DashboardSettings`, `app/modules/settings/*` |
| API-key limits | `app/modules/api_keys/service.py`, `app/modules/proxy/api_key_usage.py` |
| Request logs | `app/modules/proxy/_service/request_log.py`, `app/modules/request_logs/*`, `app/db/models.py::RequestLog` |
| Tests to extend | `tests/integration/test_v1_models.py`, `tests/integration/test_proxy_chat_completions.py`, `tests/integration/test_codex_client_compat.py`, `tests/e2e/test_openai_sdk_compat.py` |

Current routing summary:

1. `app/modules/proxy/api.py` parses OpenAI/Codex-compatible requests.
2. `request_policy.apply_api_key_enforcement()` normalizes existing GPT-5 suffix aliases and applies API-key model/reasoning/service-tier policy.
3. `_stream_responses()`, `_collect_responses()`, `_compact_responses()`, and `v1_chat_completions()` call `ProxyService` methods.
4. `ProxyService` selects a ChatGPT account, refreshes auth if needed, and calls `app/core/clients/proxy.py`.
5. `core/clients/proxy.py` talks to ChatGPT/Codex upstream endpoints such as `/codex/responses` and `/codex/responses/compact`.

The third-party route layer should sit **after public request validation/API-key public-model policy** and **before ChatGPT account selection**.

## Core design principles

1. **External model identity is public-model-first**
   - `public_model`: the model clients request and see, e.g. `gpt-5.3-codex`.
   - `target_model`: the provider model used on the wire, e.g. `minimax/minimax-m3`.
   - `provider_id`: internal provider id, e.g. `openrouter`.

2. **Model catalog remains decoupled from route targets**
   - `/v1/models` and `/backend-api/codex/models` continue to build from `ModelRegistry`.
   - Do not add OpenRouter/Minimax ids to public catalogs.
   - Route config may only map public slugs. If a mapped public slug is not currently listed, it remains hidden unless an explicit future `expose_static_public_alias` feature is added.

3. **Exact route match means provider route owns that request**
   - If a public model route matches and the endpoint is supported, use the provider.
   - Do not silently fall back to ChatGPT on provider failure unless an explicit per-route fallback policy is enabled.
   - If no route matches, leave existing `codex-lb` behavior untouched.

4. **Public policy uses public model names**
   - API-key allowed/enforced model checks must use `public_model`, not `target_model`.
   - API-key rate limits and dashboard-visible model allowlists remain meaningful to users.

5. **Internal observability must reveal actual provider**
   - External clients should not see OpenRouter/Minimax ids.
   - Internal logs/metrics/request logs should capture `provider_id` and `target_model` for debugging and cost attribution.

## Proposed architecture

### New internal components

Add a small provider-routing subsystem:

```text
app/core/external_providers/
  __init__.py
  config.py                 # parsed provider + route config dataclasses
  resolver.py               # exact public-model + endpoint route resolver
  openai_compatible.py      # OpenAI-compatible provider HTTP/SSE client
  response_rewrite.py       # model hiding and error normalization helpers
  usage.py                  # provider usage extraction/cost policy helpers

app/modules/proxy/_service/external.py
  # ProxyService mixin for external stream/collect/chat calls and request-log settlement
```

Alternative naming if preferred by maintainers: `app/core/providers/*` or `app/modules/proxy/model_routes.py`. Keep it backend-only; do not mix this with upstream proxy-pool egress (`app/core/upstream_proxy`) because that feature chooses network egress for ChatGPT accounts, not model providers.

### Data model concepts

```python
@dataclass(frozen=True)
class ExternalProviderConfig:
    id: str                       # "openrouter"
    kind: Literal["openai_compatible"]
    base_url: str                 # "https://openrouter.ai/api/v1"
    api_key_env: str              # "OPENROUTER_API_KEY"
    default_headers: Mapping[str, str]
    timeout_seconds: float
    stream_idle_timeout_seconds: float
    enabled: bool

@dataclass(frozen=True)
class ExternalModelRouteConfig:
    public_model: str             # "gpt-5.3-codex"
    provider_id: str              # "openrouter"
    target_model: str             # "minimax/minimax-m3"
    endpoints: frozenset[str]     # {"chat.completions", "responses"}
    preserve_public_model: bool   # default true
    fallback_to_codex_pool: bool  # default false
    request_overrides: Mapping[str, JsonValue]
    strip_request_fields: frozenset[str]
    pricing: ExternalPricingConfig | None
```

Endpoint names should be low-cardinality and stable:

- `chat.completions`
- `responses`
- `responses.stream`
- `responses.collect`
- `responses.compact`
- `responses.websocket`
- `audio.transcriptions`
- `images.generations`
- `images.edits`

### Config proposal

#### Phase 1: env/static config

Follow existing `Settings` patterns in `app/core/config/settings.py`: env prefix `CODEX_LB_`, JSON string parsed by field validator, `extra="ignore"`.

Example:

```bash
export OPENROUTER_API_KEY="sk-or-..."

export CODEX_LB_EXTERNAL_PROVIDERS_JSON='{
  "openrouter": {
    "kind": "openai_compatible",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
    "default_headers": {
      "HTTP-Referer": "https://github.com/Soju06/codex-lb",
      "X-Title": "codex-lb"
    },
    "timeout_seconds": 600,
    "stream_idle_timeout_seconds": 600,
    "enabled": true
  }
}'

export CODEX_LB_EXTERNAL_MODEL_ROUTES_JSON='{
  "gpt-5.3-codex": {
    "provider_id": "openrouter",
    "target_model": "minimax/minimax-m3",
    "endpoints": ["chat.completions", "responses"],
    "preserve_public_model": true,
    "fallback_to_codex_pool": false
  }
}'
```

Validation rules:

- Provider id and public model slugs must be non-empty and normalized.
- Route `provider_id` must reference an enabled provider.
- `api_key_env` must be present in the environment at request time or startup validation should mark the route disabled with an operator warning.
- `base_url` must be `https://` by default; allow `http://` only for local test/mock providers via explicit `allow_insecure_base_url`.
- Route keys are exact public model slugs after existing alias canonicalization.

#### Phase 2: dashboard/runtime config

Add dashboard controls after backend behavior is proven:

- Provider list: id, base URL, API key env name, optional default headers, enabled.
- Route list: public model, provider, target model, endpoints, fallback policy, enabled.
- Secrets: keep provider keys in env by default. If dashboard-managed keys are desired later, store encrypted values using the existing `TokenEncryptor` pattern.

Potential DB columns/tables:

- MVP dashboard-lite: add `external_providers_json` and `external_model_routes_json` to `DashboardSettings`.
- More maintainable: add normalized tables:
  - `external_providers(id, kind, base_url, api_key_env, default_headers_json, is_active, created_at, updated_at)`
  - `external_model_routes(public_model, provider_id, target_model, endpoints_json, preserve_public_model, fallback_to_codex_pool, is_active, created_at, updated_at)`

Use normalized tables if the dashboard is expected to manage many routes; use JSON settings only for a fast operator-only first version.

## Routing flow

### Route lookup order

For each request with a model:

1. Parse and validate the request exactly as today.
2. Apply existing public-model normalization and API-key model enforcement.
   - Existing Cursor/GPT suffix alias logic should still convert `gpt-5.3-codex-high` to `gpt-5.3-codex` plus `reasoning.effort=high`.
3. Compute `public_model` from the canonical model after step 2.
4. Resolve `(public_model, endpoint)` in the external route resolver.
5. If no match: continue normal ChatGPT account-pool flow.
6. If match:
   - enforce API-key allowed-model/rate-limit policy against `public_model`;
   - bypass ChatGPT account selection;
   - call the provider adapter with `target_model`;
   - rewrite provider response model fields back to `public_model`;
   - record internal provider metadata.

### Why after API-key model policy?

`api_key.enforced_model` and `api_key.allowed_models` currently operate on visible model names. If route lookup happened before this policy, an enforced model could be skipped or a third-party target could leak into policy comparisons. The route layer must therefore operate on the **effective public model**.

### Fallback policy

Default:

```text
Exact route configured + provider fails -> return provider-derived OpenAI error.
No exact route configured -> normal codex-lb ChatGPT pool.
```

Optional future route setting:

```json
{"fallback_to_codex_pool": true}
```

If enabled, only retryable provider failures should fall back to the ChatGPT pool, and logs must record `fallback_reason`. Keep default false because hidden fallback can create confusing cost, quality, and data-routing behavior.

## Endpoint plan

### 1. `GET /v1/models` and `GET /backend-api/codex/models`

Do not change the default model list behavior.

Implementation notes:

- Keep `_build_models_response()` and `_build_codex_models_response()` based on `get_model_registry().get_models_with_fallback()`.
- API-key model filtering remains based on public slugs.
- Do not emit provider ids or target model ids.
- Optionally add an internal-only health/admin endpoint later to show route status.

Tests:

- Configured route `gpt-5.3-codex -> openrouter:minimax/minimax-m3` does not add `minimax/minimax-m3` to `/v1/models`.
- `/v1/models` still returns `gpt-5.3-codex` metadata from registry/bootstrap.
- API-key allowed model filtering still filters public slugs.

### 2. `POST /v1/chat/completions`

This is the best first production endpoint because OpenRouter is strongly OpenAI Chat Completions compatible.

Current behavior:

- `v1_chat_completions()` validates `ChatCompletionsRequest`.
- It converts chat to internal `ResponsesRequest` and uses ChatGPT `/codex/responses`.
- The response is converted back to Chat Completions.

Proposed external route behavior:

- Branch before ChatGPT account selection.
- For external routes, call provider `/chat/completions` directly with:
  - inbound chat payload normalized/validated by `ChatCompletionsRequest`;
  - `model` rewritten from `public_model` to `target_model`;
  - request headers sanitized;
  - provider auth headers applied.
- Preserve `stream=true` behavior by proxying provider SSE and rewriting each JSON chunk's `model` field to `public_model`.
- For non-streaming, return provider JSON with `model` rewritten to `public_model`.
- Normalize provider error envelopes into OpenAI error envelopes.

Policy work needed:

- Extract model/reasoning/service-tier policy helpers from `request_policy.py` so chat direct-provider flow can enforce API-key model policy without forcing Responses conversion for the provider payload.
- Keep strict function-tool schema pre-validation exactly as current `v1_chat_completions()` does.
- Preserve existing provider-specific `thinking`/`enable_thinking` alias normalization expectations.

Tests:

- Streaming chat chunks preserve `[DONE]` and hide provider model.
- Non-streaming response hides provider model.
- Provider error returns OpenAI error envelope.
- `allowed_models=["gpt-5.3-codex"]` allows the external route; `allowed_models=["gpt-5.4"]` rejects it.
- `enforced_model="gpt-5.3-codex"` routes to provider even if client requested another public model.

### 3. `POST /v1/responses` and `POST /backend-api/codex/responses`

Current behavior:

- Public `/v1/responses` converts to internal `ResponsesRequest`, streams through `ProxyService`, and normalizes SSE events for OpenAI SDK compatibility.
- `/backend-api/codex/responses` preserves more Codex-native events and semantics.
- HTTP requests often use the server-side HTTP responses bridge for upstream continuity.

Proposed external route behavior:

- If route supports `responses`, send provider-compatible request to provider `/responses` with `model=target_model`.
- Stream provider SSE back through existing public normalization where possible.
- Rewrite model fields in:
  - terminal `response` objects;
  - `response.created`, `response.in_progress`, `response.completed`, `response.failed`, etc.;
  - any top-level `model` fields if present.
- Do not use HTTP bridge for external provider routes unless a provider-specific bridge is implemented. External providers should be simple stateless HTTP/SSE pass-through initially.
- Do not run ChatGPT account selection, continuity-owner resolution, or ChatGPT account health penalties for external routes.

Compatibility concerns:

- OpenRouter support for `/responses` may vary by model/provider. Make endpoint support explicit in route config.
- If a route maps a model but does not include `responses`, a `/v1/responses` request should return a deterministic 501/400 OpenAI error such as `external_route_endpoint_unsupported` rather than silently using ChatGPT.
- `/backend-api/codex/responses` clients may expect Codex-specific behavior. Treat backend Codex route support as opt-in per route until verified.

Tests:

- `/v1/responses` streaming starts with valid OpenAI Responses events and hides provider target model.
- Non-streaming `/v1/responses` collect path hides provider model.
- Provider route does not require any ChatGPT account to exist.
- Provider route does not emit `no_accounts`.
- Unsupported endpoint returns deterministic OpenAI error.

### 4. `POST /v1/responses/compact` and `/backend-api/codex/responses/compact`

This is the hardest Codex-specific surface.

Current behavior:

- Compact calls upstream ChatGPT/Codex `/codex/responses/compact`.
- It returns an opaque `response.compact*` payload that Codex clients use as canonical compacted context.

Provider options:

1. **Provider pass-through compact**
   - Use only if the external provider supports an equivalent `/responses/compact` contract.
   - Most OpenAI-compatible providers probably do not.

2. **Synthetic compact**
   - Locally build a compaction prompt and call provider chat/responses to summarize context.
   - Return a `response.compaction`-compatible payload.
   - Risk: may not match Codex's expected compact state exactly.

3. **Route compact back to ChatGPT pool**
   - Lets Codex CLI continue compacting via ChatGPT while normal generation uses external provider.
   - Risk: mixed-provider context semantics and data-routing surprise.
   - Should require explicit `compact_strategy="codex_pool"` and clear logs.

Recommended phased approach:

- Phase 1: mark compact unsupported for external routes unless explicitly configured.
- Phase 2: implement `compact_strategy="codex_pool"` for operators who accept mixed-provider compaction.
- Phase 3: implement synthetic compact only after confirming Codex client expectations and adding robust contract tests.

### 5. WebSocket `/v1/responses` and `/backend-api/codex/responses`

Current behavior is complex and deeply tied to ChatGPT upstream WebSockets and continuity state.

Plan:

- Do not support external provider WebSockets in the first backend implementation unless the target provider has a documented compatible websocket endpoint.
- For websocket clients requesting an externally mapped model, either:
  - return a deterministic unsupported route error during websocket accept/first request; or
  - internally bridge downstream websocket messages to provider HTTP/SSE if that preserves client contract.
- Treat this as a later phase after HTTP/SSE is stable.

### 6. Audio, images, embeddings, files, and other OpenAI surfaces

Current `codex-lb` supports:

- `/v1/audio/transcriptions`
- `/v1/images/generations`
- `/v1/images/edits`
- `/backend-api/files*`
- Codex control surfaces

Recommended behavior:

- Only route endpoints that are explicitly declared in the external route config.
- Model-specific image routes should remain under existing image service unless a future image-provider route is configured.
- Transcriptions can be routed by public transcription model if provider supports OpenAI-compatible `/audio/transcriptions`.
- Embeddings are not currently visible in the inspected route list; if added later, include the same resolver pattern.

## Provider client design

### OpenAI-compatible provider adapter

Implement a reusable `OpenAICompatibleProviderClient` around `aiohttp` or the existing shared HTTP session utilities.

Responsibilities:

- Build provider URL: `base_url.rstrip("/") + endpoint_path`.
- Add `Authorization: Bearer <provider_key>`.
- Apply default headers from config.
- Drop inbound client auth and proxy-only headers.
- Rewrite request model to `target_model`.
- Stream provider SSE without buffering entire response.
- Normalize provider errors to OpenAI envelopes.
- Rewrite response model fields back to `public_model`.
- Enforce configured timeouts and max SSE event size.
- Redact provider credentials in logs/archive.

### SSE model rewrite rules

For each SSE block:

- Preserve non-JSON lines and `[DONE]`.
- For `data: <json>`, recursively rewrite selected model fields:
  - top-level `model` when value equals target model;
  - `response.model` if present;
  - `error` untouched unless it embeds target model in safe-to-rewrite message text; avoid message text rewrites initially.
- Preserve event names and sequence numbers.
- Do not inject Codex vendor events for `/v1`; public normalization already handles OpenAI Responses compatibility.

### Request field normalization

Provider route config should support minimal field handling:

```json
{
  "strip_request_fields": ["store", "parallel_tool_calls"],
  "request_overrides": {
    "provider": {"order": ["MiniMax"]}
  }
}
```

Keep default behavior conservative: send only fields the endpoint normally accepts. Avoid broad provider-specific rewrites until tests prove them.

## API-key rate limiting and accounting

### Preserve API-key semantics

For external routes:

- `allowed_models`, `enforced_model`, `enforced_reasoning_effort`, and `enforced_service_tier` should use public model names.
- API-key request reservations should still be created and finalized where usage is available.
- Account assignment scope should not apply because no ChatGPT account is selected. If an API key has account-assignment scope enabled, define behavior explicitly:
  - Recommended default: external routes ignore account assignment scope but still honor API-key model/rate limits.
  - Alternative strict mode: account-scoped API keys cannot use external routes unless a future provider-assignment scope exists.

### Usage settlement

Provider usage formats differ by endpoint:

- Chat Completions: `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`.
- Responses: `usage.input_tokens`, `usage.output_tokens`, `usage.total_tokens`.

Add a helper that converts provider usage into existing reservation finalization fields:

```text
input_tokens          <- prompt_tokens or input_tokens
output_tokens         <- completion_tokens or output_tokens
cached_input_tokens   <- prompt_tokens_details.cached_tokens or input_tokens_details.cached_tokens
reasoning_tokens      <- completion_tokens_details.reasoning_tokens or output_tokens_details.reasoning_tokens
```

If usage is missing:

- Non-streaming: release reservation or finalize with an estimated low value depending on existing API-key policy.
- Streaming: collect final usage chunk when present; otherwise release reservation or use request estimate. Prefer release for MVP to avoid overbilling hidden-provider calls.

### Cost attribution

Do not blindly price provider calls with OpenAI public model pricing if operators need accurate cost.

Route config should support:

```json
"pricing": {
  "mode": "provider_custom",
  "input_per_1m": 0.2,
  "output_per_1m": 1.1,
  "cached_input_per_1m": 0.0
}
```

MVP options:

- `mode="public_model"`: use existing public model pricing for dashboard continuity.
- `mode="provider_custom"`: use explicit provider price fields.
- `mode="none"`: track tokens but no cost.

Default should be `none` or `public_model` depending on operator preference; document the tradeoff.

## Request logs, metrics, and observability

### RequestLog additions

Current `RequestLog` stores `model`, `account_id`, `transport`, service tier, tokens, error data, and upstream proxy route metadata. Add internal provider metadata while keeping `model` as the public model.

Proposed new nullable columns:

- `external_provider_id`
- `external_provider_model`
- `external_route_public_model`
- `external_route_endpoint`
- `external_fallback_used`
- `external_fallback_reason`

Alternative if schema churn should be minimized: encode in `source` and `failure_detail` first, then add columns later. Columns are better for dashboard filters and metrics.

### Logs

Emit structured low-cardinality logs:

```text
external_model_route_resolved request_id=... public_model=gpt-5.3-codex provider_id=openrouter endpoint=chat.completions
external_provider_request_started request_id=... provider_id=openrouter endpoint=chat.completions target_host=openrouter.ai
external_provider_request_completed request_id=... provider_id=openrouter status=200 latency_ms=... input_tokens=... output_tokens=...
external_provider_request_failed request_id=... provider_id=openrouter error_code=... status=...
```

Do not log provider API keys, raw request payloads, prompt text, or full custom headers unless existing explicit payload tracing flags are enabled and redaction is applied.

### Metrics

If Prometheus is enabled, add counters/histograms:

- `codex_lb_external_route_requests_total{provider,endpoint,status}`
- `codex_lb_external_route_latency_seconds{provider,endpoint}`
- `codex_lb_external_route_errors_total{provider,endpoint,error_code}`
- `codex_lb_external_route_fallback_total{provider,endpoint,reason}`
- `codex_lb_external_route_tokens_total{provider,token_type}`

Keep labels low cardinality. Do not label by `target_model` unless cardinality is bounded.

## Security and privacy

- Provider keys live in environment variables for MVP.
- Do not echo provider ids or target models to clients.
- Redact provider auth/default headers in logs and conversation archive.
- Add `https://` validation for provider base URLs.
- Make external routing opt-in; no provider traffic should occur with empty config.
- Consider a warning in dashboard/settings that external routes send prompts to a third-party provider.
- Internal logs should be transparent enough to avoid operator self-deception: even if clients see `gpt-5.3-codex`, logs must show OpenRouter/Minimax was used.

## Failure behavior

| Situation | Recommended response |
|---|---|
| No matching route | Existing ChatGPT pool behavior |
| Route matches but provider disabled | 503 OpenAI error `external_provider_unavailable` |
| Route matches but API key env missing | 503 OpenAI error `external_provider_unavailable` |
| Route matches but endpoint unsupported | 501/400 OpenAI error `external_route_endpoint_unsupported` |
| Provider 4xx | Preserve provider error envelope when safe, hide target model, same status |
| Provider 429 | Return 429 `rate_limit_error`; do not mark ChatGPT accounts unhealthy |
| Provider 5xx/timeout | Return 502/503 `server_error`/`upstream_unavailable`; optional provider retry |
| Provider stream ends without terminal event | Emit OpenAI-compatible stream failure (`stream_incomplete` or provider error) |
| Fallback enabled and provider retryable failure | Retry ChatGPT pool, log fallback, keep public model |

Provider failures must not penalize ChatGPT accounts or mutate account health/cooldown state.

## Implementation phases

### Phase 0 — OpenSpec and contract decisions

Create proper OpenSpec artifacts from this plan:

- `proposal.md`
- `tasks.md`
- spec deltas for:
  - `model-catalog-compat`
  - `chat-completions-compat`
  - `responses-api-compat`
  - `api-keys`
  - `proxy-runtime-observability`
  - optionally a new `external-model-routing` capability

Decide before coding:

- Whether compact routes should fail, use ChatGPT pool, or synthetic compact.
- Whether account-scoped API keys may use external routes.
- Whether provider cost defaults to `none`, `public_model`, or custom-only.

### Phase 1 — Config + resolver + model catalog invariants

- Add `ExternalProviderConfig` and `ExternalModelRouteConfig` parsing in `Settings`.
- Add exact route resolver.
- Add startup/operator validation logs.
- Add tests proving `/v1/models` and `/backend-api/codex/models` are unchanged by route config.
- Add tests for exact matching and alias canonicalization.

Deliverable: configured routes are visible internally but no traffic is routed yet.

### Phase 2 — `/v1/chat/completions` via OpenRouter

- Add OpenAI-compatible provider client for chat completions.
- Add streaming and non-streaming response model rewrite.
- Integrate branch in `v1_chat_completions()` before ChatGPT account selection.
- Preserve API-key limits and request logs.
- Add mock OpenRouter tests.

Deliverable: OpenCode/OpenAI SDK chat-completions clients can use `gpt-5.3-codex` while requests go to OpenRouter Minimax.

### Phase 3 — `/v1/responses` HTTP/SSE

- Add provider `/responses` stream/collect support.
- Add route branch in `_stream_responses()` and `_collect_responses()` after public policy and before bridge/account selection.
- Reuse public stream normalization where possible.
- Ensure no-account startup works for external routes.
- Add OpenAI Python SDK compatibility tests.

Deliverable: OpenAI Responses API clients can use external route mappings.

### Phase 4 — Codex-native routes

- Evaluate `/backend-api/codex/responses` with Codex CLI against provider `/responses`.
- Decide behavior for Codex-specific event expectations.
- Implement compact strategy:
  - unsupported by default;
  - optional `codex_pool` compact fallback;
  - synthetic compact later if needed.
- Evaluate websocket bridge only after HTTP/SSE works.

Deliverable: Codex CLI support is explicit and documented, not accidental.

### Phase 5 — Dashboard/admin management

- Add backend admin APIs for providers/routes if desired.
- Add frontend settings panel under Routing or APIs.
- Add validation UX and route health indicators.
- Keep provider keys env-only unless encrypted secret storage is explicitly requested.

Deliverable: operators can manage mappings without editing env JSON, if desired.

### Phase 6 — Hardening

- Provider circuit breaker.
- Optional fallback chains.
- Provider health endpoint/admin status.
- Conversation archive provider metadata with redacted secrets.
- Provider-specific request field compatibility profiles.
- Load tests for streaming cancellation and slow streams.

## Concrete code touchpoints

### `app/core/config/settings.py`

Add JSON settings and validators:

- `external_providers_json`
- `external_model_routes_json`

Use `Annotated[..., NoDecode]` only if direct env parsing needs it; existing validators parse JSON strings for complex fields like `model_context_window_overrides`.

### `app/modules/proxy/request_policy.py`

Refactor carefully:

- Keep existing GPT-5 suffix alias behavior.
- Add helpers that return public policy decisions without always mutating provider-bound payloads.
- Ensure `resolve_model_alias()` remains public-model-only and never returns target provider model ids.

### `app/modules/proxy/api.py`

Add route checks in:

- `v1_chat_completions()`
- `_stream_responses()`
- `_collect_responses()`
- `_compact_responses()` only after compact strategy decision
- transcription/images endpoints only if route support is added

Avoid changing `_build_models_response()` except tests to prove it stays unchanged.

### `app/modules/proxy/service.py` and `_service/*`

Add external route service methods or a mixin:

- `stream_external_responses(...)`
- `collect_external_responses(...)`
- `stream_external_chat_completions(...)`
- `collect_external_chat_completions(...)`

These methods should not call `_select_account_with_budget*`.

### `app/core/clients/proxy.py`

Do not overload ChatGPT/Codex upstream functions with provider behavior. Add a separate provider client module to avoid confusing ChatGPT account auth with provider API-key auth.

### `app/db/models.py` and migrations

If adding request-log columns, add Alembic migration and integration migration tests.

### Frontend

Only in dashboard phase:

- `frontend/src/features/settings/schemas.ts`
- `frontend/src/features/settings/api.ts`
- `frontend/src/features/settings/components/routing-settings.tsx` or a new `external-provider-routing-settings.tsx`
- tests under `frontend/src/features/settings/components/*.test.tsx`

## Test plan

### Unit tests

- Config parsing:
  - valid provider/route JSON;
  - invalid provider id;
  - missing provider reference;
  - insecure URL rejection;
  - disabled provider route ignored.
- Resolver:
  - exact public model match;
  - no wildcard/substring match;
  - canonical alias behavior;
  - endpoint support match.
- Response rewrite:
  - chat JSON model rewrite;
  - chat SSE chunk model rewrite;
  - Responses event model rewrite;
  - `[DONE]` preserved;
  - invalid SSE JSON preserved or error-normalized as intended.
- Provider error mapping.

### Integration tests

- `/v1/models` unchanged by external routes.
- `/backend-api/codex/models` unchanged by external routes.
- `/v1/chat/completions` non-streaming routes to mock provider and hides target model.
- `/v1/chat/completions` streaming routes to mock provider and hides target model.
- `/v1/responses` stream routes to mock provider when endpoint is enabled.
- `/v1/responses` rejects with endpoint unsupported when route lacks `responses` support.
- External route works with no ChatGPT accounts configured.
- Normal route still returns `no_accounts` when no account exists and no external route matches.
- API-key allowed/enforced model behavior uses public model.
- Request logs include provider metadata internally.
- Provider 429/5xx does not mark any ChatGPT account unhealthy.

### E2E/contract tests

- OpenAI Python SDK:
  - `client.chat.completions.create(stream=True/False)`.
  - `client.responses.create(stream=True/False)` if provider supports `/responses`.
- OpenCode/Cursor compatibility for chat completions.
- Codex CLI only after compact/backend route decision.

### Verification commands

Use repo-standard checks:

```bash
uv run --frozen ruff check app tests
uv run --frozen ruff format --check app tests
uv run --frozen ty check app
uv run --frozen pytest tests/unit -q
uv run --frozen pytest tests/integration/test_v1_models.py -q
uv run --frozen pytest tests/integration/test_proxy_chat_completions.py -q
uv run --frozen pytest tests/integration/test_codex_client_compat.py -q
```

Add targeted tests as implementation progresses.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Provider target model leaks to client responses | Central response/SSE rewrite tests; keep `model` request-log public separately from provider metadata |
| `/v1/models` accidentally exposes OpenRouter models | Do not merge provider models into `ModelRegistry`; invariant tests |
| API-key allowed models compare against target provider ids | Run route lookup after public policy; tests for allowed/enforced models |
| Codex CLI breaks on compact | Treat compact support as separate phase; fail deterministically or configure explicit strategy |
| Provider lacks `/responses` support | Endpoint support is explicit per route; deterministic unsupported error |
| Cost dashboard becomes misleading | Add provider pricing policy and internal provider metadata |
| Hidden fallback causes surprising data/cost routing | Default fallback disabled; require explicit config and logs |
| Provider API key leaked in logs/archive | Redaction tests; use existing archive header redaction patterns |
| External provider failures pollute ChatGPT account health | Separate provider client path; no account-health writes for external routes |
| Dashboard/runtime settings add schema risk | Start env-only; add dashboard after backend is stable |

## Example MVP configuration

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
    "endpoints": ["chat.completions"],
    "preserve_public_model": true
  }
}'
```

Expected MVP behavior:

```text
GET /v1/models
  -> includes gpt-5.3-codex; does not include minimax/minimax-m3

POST /v1/chat/completions {"model":"gpt-5.3-codex", ...}
  -> OpenRouter request model minimax/minimax-m3
  -> client response model gpt-5.3-codex

POST /v1/chat/completions {"model":"gpt-5.4", ...}
  -> existing ChatGPT account-pool flow
```

## Recommended next step

Turn this plan into an OpenSpec change with normative requirements, then implement Phase 1 and Phase 2 first. That gives immediate OpenRouter/Minimax value for OpenAI-compatible chat clients while keeping model catalogs, account-pool routing, and Codex-specific compact/websocket behavior safe until explicitly handled.
