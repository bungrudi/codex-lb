## 1. OpenSpec

- [x] 1.1 Promote `plan.md` into proposal, design notes, and normative spec deltas.
- [x] 1.2 Validate `add-third-party-model-routing` with `openspec validate add-third-party-model-routing --strict`.

## 2. Configuration and resolver

- [x] 2.1 Add external provider and model-route config parsing with validation for provider ids, route provider references, endpoint names, provider base URLs, and API-key env names.
- [x] 2.2 Implement an exact public-model plus endpoint route resolver that runs after public model alias normalization and API-key model enforcement.
- [x] 2.3 Add unit tests for config parsing, route matching, endpoint matching, disabled providers, missing provider keys, and default no-config behavior.

## 3. Provider client and response rewriting

- [x] 3.1 Add an OpenAI-compatible provider HTTP/SSE client that uses configured base URLs, provider auth, default headers, timeouts, and sanitized inbound headers.
- [x] 3.2 Add response and SSE rewriting helpers that hide target provider model ids behind the public requested model while preserving OpenAI event contracts and `[DONE]` frames.
- [x] 3.3 Add provider error normalization and secret redaction coverage.

## 4. Chat Completions route

- [x] 4.1 Route configured `/v1/chat/completions` requests to the provider before ChatGPT account selection.
- [x] 4.2 Preserve existing chat request validation, strict tool-schema validation, provider-thinking alias normalization, streaming chunks, non-streaming responses, and OpenAI error envelopes.
- [x] 4.3 Add integration/e2e tests for streaming, non-streaming, provider errors, no-ChatGPT-account operation, API-key allowlists, and enforced-model routing.

## 5. Responses HTTP/SSE route

- [x] 5.1 Route configured HTTP `/v1/responses` and explicitly enabled backend Codex Responses requests to provider `/responses` without using ChatGPT account selection or the HTTP bridge.
- [x] 5.2 Return deterministic unsupported-endpoint errors for matching routes that do not enable Responses, compact, or websocket support.
- [x] 5.3 Add OpenAI SDK compatibility tests for streaming and non-streaming Responses where the provider endpoint is enabled.
- [x] 5.4 Bridge Codex Computer Use MCP tool calls for externally routed backend Responses requests.

## 6. API-key accounting and request logs

- [x] 6.1 Enforce allowed/enforced model policy and model-scoped limits using the public model for external routes.
- [x] 6.2 Settle API-key reservations from provider usage fields when available and release exactly once when usage is unavailable or the route fails before provider usage is known.
- [x] 6.3 Persist request logs with public `model`, `account_id = NULL`, and internal provider metadata.
- [x] 6.4 Add Alembic migration and migration tests for any new request-log columns.

## 7. Observability and safeguards

- [x] 7.1 Add low-cardinality logs/metrics for route resolution, provider request lifecycle, provider errors, provider token totals, and optional fallback.
- [x] 7.2 Ensure provider errors do not mutate ChatGPT account health, cooldown, quota, or selection state.
- [x] 7.3 Ensure provider keys and credential-bearing provider headers are redacted in logs and conversation archives.

## 8. Optional follow-up surfaces

- [ ] 8.1 Decide and implement compact strategy (`unsupported`, `codex_pool`, provider pass-through, or synthetic compact) with contract tests.
- [ ] 8.2 Decide and implement websocket behavior for externally routed models with Codex CLI/OpenAI SDK tests.
- [ ] 8.3 Add dashboard/admin management for providers and routes if operator runtime management is required.

## 9. Verification

- [x] 9.1 Run `openspec validate add-third-party-model-routing --strict` and `openspec validate --specs`.
- [x] 9.2 Run backend format/type/test checks for touched code.
- [ ] 9.3 Run targeted OpenAI SDK/OpenCode/Codex client compatibility checks for enabled endpoints.
