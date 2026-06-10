## ADDED Requirements

### Requirement: External model routes are opt-in exact public-model mappings

The system SHALL support opt-in external model routing configuration that maps an exact public model id and endpoint to an OpenAI-compatible provider id and provider target model id. When no external provider route is configured for the request's effective public model and endpoint, the system MUST preserve the existing ChatGPT account-pool routing behavior.

External route matching MUST use the canonical public model id after existing public model alias normalization and API-key model enforcement. Matching MUST be exact; wildcard, prefix, substring, and implicit provider-model matches MUST NOT be applied.

Provider configuration MUST include a provider id, provider kind, base URL, API-key environment variable name, enabled flag, and optional default headers/timeouts. Provider base URLs MUST use HTTPS unless an explicit local-test insecure mode is configured.

#### Scenario: No external routes preserves existing routing

- **GIVEN** external model routing is not configured
- **WHEN** a client sends a proxy request for `gpt-5.3-codex`
- **THEN** the request follows the existing ChatGPT account-pool routing path
- **AND** no external provider request is opened

#### Scenario: Exact public model and endpoint route matches

- **GIVEN** an enabled route maps public model `gpt-5.3-codex` and endpoint `chat.completions` to provider `openrouter` target model `minimax/minimax-m3`
- **WHEN** a client sends `POST /v1/chat/completions` with model `gpt-5.3-codex`
- **THEN** the route resolver selects the `openrouter` route
- **AND** the provider request uses target model `minimax/minimax-m3`

#### Scenario: Non-matching endpoint does not silently route

- **GIVEN** an enabled route maps public model `gpt-5.3-codex` only for endpoint `chat.completions`
- **WHEN** a client sends `POST /v1/responses` with model `gpt-5.3-codex`
- **THEN** the system returns an OpenAI-format error with code `external_route_endpoint_unsupported`
- **AND** the request does not fall through to the ChatGPT account pool unless explicit fallback is configured for that route and failure class

#### Scenario: Similar target model does not match by substring

- **GIVEN** a route maps public model `gpt-5.3-codex` to target model `minimax/minimax-m3`
- **WHEN** a client requests model `minimax/minimax-m3` directly
- **THEN** the external route does not match
- **AND** the provider target model id is not treated as a public model alias

### Requirement: Dashboard settings manage external providers and model routes

The dashboard SHALL expose external model routing management from the existing Settings area rather than a separate standalone GUI. Authenticated dashboard operators MUST be able to create, update, list, enable, disable, and delete OpenAI-compatible external provider records and named exact public-model route profile records.

Dashboard-managed provider API keys SHALL be stored encrypted with the existing application encryption-key mechanism. Admin API and dashboard responses MUST return only secret status metadata such as whether a key is configured; they MUST NOT return raw provider API keys. Updating a provider without an API-key field MUST preserve the existing encrypted key. An explicit key-clear action MUST remove the stored key.

The runtime route resolver MUST include dashboard-managed providers and active route profiles without requiring process restart. Dashboard-managed provider rows MUST take precedence over environment-provided providers with the same provider id. Active dashboard-managed route profiles MUST take precedence over environment-provided routes for the same public model and endpoint. Dashboard changes MUST invalidate any external routing cache so the next proxy request observes the new provider or route state.

Dashboard-managed route profiles MUST use the same validation and routing semantics as environment-configured routes: exact public model ids, explicit endpoint lists, supported provider references, HTTPS provider base URLs unless local insecure mode is explicitly enabled, fallback disabled unless implemented, public model policy enforcement, client-visible public model identity preservation, and deterministic unsupported-endpoint errors.

The dashboard MUST allow multiple saved route profiles for the same public model so operators can switch between provider targets without deleting configuration. More than one route profile MAY be active for the same public model only when their enabled endpoint sets are disjoint. Activating a route profile MUST deactivate any other active dashboard-managed route profile whose public model and endpoint set overlap with the activated profile, unless the request explicitly asks to leave conflicts unresolved and receives a validation error. The resolver MUST fail closed with a deterministic external-route conflict error if persisted configuration still contains multiple active dashboard-managed route profiles for the same public model and endpoint.

#### Scenario: Operator creates a provider and route profile from Settings

- **GIVEN** no process restart occurs after startup
- **WHEN** an authenticated dashboard operator creates an enabled provider with an encrypted API key
- **AND** creates an active route profile mapping public model `gpt-5.3-codex` to that provider target model `minimax/minimax-m3` for endpoint `backend.responses`
- **THEN** the next matching backend Codex Responses request routes to the configured provider target model
- **AND** the client-visible response still uses public model `gpt-5.3-codex`

#### Scenario: Dashboard responses redact provider secrets

- **GIVEN** a dashboard-managed provider has an encrypted provider API key
- **WHEN** an operator lists or reads external provider routing settings
- **THEN** the response indicates that the provider key is configured
- **AND** the response does not include the raw provider API key
- **AND** credential-bearing provider headers are not exposed as raw secret values

#### Scenario: Dashboard config takes precedence over environment config

- **GIVEN** environment config maps public model `gpt-5.3-codex` to one provider target for endpoint `chat.completions`
- **AND** dashboard config has an active route profile for public model `gpt-5.3-codex` to a different provider target for endpoint `chat.completions`
- **WHEN** a client sends a matching proxy request
- **THEN** the dashboard-managed route profile is selected
- **AND** the environment route for the same public model and endpoint is not used

#### Scenario: Activating one profile deactivates overlapping profiles only

- **GIVEN** public model `gpt-5.3-codex` has an active `Minimax` route profile for endpoint `backend.responses`
- **AND** it has an inactive `DeepSeek V4 Pro` route profile for endpoint `backend.responses`
- **WHEN** an operator activates the `DeepSeek V4 Pro` route profile with conflict deactivation enabled
- **THEN** the `DeepSeek V4 Pro` profile becomes active
- **AND** the `Minimax` profile becomes inactive
- **AND** active route profiles for other public models remain active
- **AND** active route profiles for `gpt-5.3-codex` with disjoint endpoints remain active

#### Scenario: Persisted active conflict fails closed

- **GIVEN** persisted dashboard configuration contains two active route profiles for `gpt-5.3-codex` and endpoint `responses`
- **WHEN** a client sends a matching Responses request
- **THEN** the system returns an OpenAI-format error with code `external_route_conflict`
- **AND** the request is not sent to any external provider or ChatGPT account pool

#### Scenario: Dashboard-admin endpoints require dashboard authentication

- **WHEN** an unauthenticated request attempts to create, update, delete, or list dashboard-managed external providers or routes
- **THEN** the system rejects the request using the existing dashboard authentication error contract
- **AND** no provider or route configuration is changed

### Requirement: External provider routes preserve public model identity externally

For provider-routed requests, the system MUST keep the client-visible model identity equal to the effective public model id. The outbound provider request MUST use the configured provider target model id, but client-facing JSON responses, streaming SSE JSON payloads, and collected response payloads MUST replace provider target model fields with the public model id wherever the provider emits a model field for the request model.

The system MUST NOT expose provider ids, provider API-key env names, provider base URLs, or provider target model ids in public model-list responses or successful proxy responses.

#### Scenario: Non-streaming provider response hides target model

- **GIVEN** public model `gpt-5.3-codex` routes to target model `minimax/minimax-m3`
- **WHEN** the provider returns a non-streaming response with `model: "minimax/minimax-m3"`
- **THEN** the client response contains `model: "gpt-5.3-codex"`
- **AND** the client response does not contain `minimax/minimax-m3`

#### Scenario: Streaming provider chunks hide target model

- **GIVEN** public model `gpt-5.3-codex` routes to target model `minimax/minimax-m3`
- **WHEN** the provider streams SSE JSON chunks with `model: "minimax/minimax-m3"`
- **THEN** each forwarded client-visible JSON chunk contains `model: "gpt-5.3-codex"`
- **AND** non-JSON SSE frames and `data: [DONE]` are preserved

#### Scenario: Internal diagnostics may reveal actual route

- **WHEN** an external provider route is used
- **THEN** internal request logs and operator diagnostics MAY record provider id and target model id
- **AND** those internal fields MUST NOT be emitted in successful client payloads

### Requirement: OpenAI-compatible provider requests use provider credentials and sanitized headers

External provider requests SHALL be sent through an OpenAI-compatible provider adapter. The adapter MUST construct URLs from the configured provider base URL and endpoint path, authenticate with the provider API key read from the configured environment variable, apply configured default provider headers, and remove downstream client authentication, hop-by-hop, proxy-only, and ChatGPT account headers before opening the provider request.

Credential-bearing provider headers and API-key values MUST be redacted in logs, metrics, and conversation archives.

#### Scenario: Provider request uses provider auth rather than client auth

- **GIVEN** a client request includes a `codex-lb` Bearer API key
- **AND** the selected provider config uses `api_key_env = "OPENROUTER_API_KEY"`
- **WHEN** the external provider request is opened
- **THEN** the outbound provider `Authorization` header uses the value from `OPENROUTER_API_KEY`
- **AND** the downstream `codex-lb` API key is not forwarded to the provider

#### Scenario: Provider credentials are redacted

- **WHEN** provider request tracing or conversation archive is enabled
- **THEN** provider credential-bearing headers are stored as redacted values
- **AND** raw provider API-key values are not written to logs or archive records

### Requirement: External provider failures are isolated from ChatGPT account state

External provider requests MUST NOT select a ChatGPT account, refresh ChatGPT account tokens, consume ChatGPT account concurrency leases, or mark ChatGPT accounts unhealthy. Provider 4xx, 429, 5xx, timeout, and stream-incomplete failures MUST be surfaced as OpenAI-compatible errors for the client-visible endpoint.

When a matching external route fails, fallback to the ChatGPT account pool MUST be disabled by default. If a route explicitly enables fallback, the system MUST only fallback for retryable provider failures and MUST record the fallback reason in operator diagnostics and request logs.

#### Scenario: External route works with no ChatGPT accounts

- **GIVEN** no ChatGPT accounts are configured
- **AND** an enabled external route exists for public model `gpt-5.3-codex` and endpoint `chat.completions`
- **WHEN** a client sends a matching request
- **THEN** the request is sent to the external provider
- **AND** the response is not `no_accounts`

#### Scenario: Provider rate limit does not penalize ChatGPT accounts

- **WHEN** an external provider returns a 429 rate-limit response
- **THEN** the client receives an OpenAI-compatible 429 response
- **AND** no ChatGPT account health, cooldown, quota, or selection state is mutated

#### Scenario: Fallback disabled by default

- **GIVEN** an external route does not enable fallback
- **WHEN** the provider returns a retryable 5xx error
- **THEN** the system returns an OpenAI-compatible provider failure to the client
- **AND** the system does not retry the request through the ChatGPT account pool

### Requirement: External backend Responses routes bridge Codex Computer Use MCP tools

When an enabled external route handles a backend Codex Responses request whose payload includes Codex Computer Use plugin context, the system SHALL bridge the Computer Use MCP tool namespace to OpenAI-compatible function tools for the provider request. The bridge MUST expose provider-visible function tool definitions for the Computer Use MCP tools and MUST NOT expose provider ids, provider target model ids, or provider credentials to the client.

For bridged provider responses, the system MUST rewrite provider-visible Computer Use function calls back to Codex's client-visible MCP namespace shape before forwarding the response to the client. The system MUST preserve call ids and arguments so the Codex client can execute the MCP tool and return the corresponding tool output. The bridge MUST rewrite prior client-visible Computer Use MCP function-call items back to the provider-visible function names on subsequent provider requests so provider tool-call continuity is preserved.

#### Scenario: Minimax-compatible Computer Use tool call is forwarded as Codex MCP namespace

- **GIVEN** public model `gpt-5.3-codex` routes backend Codex Responses requests to an OpenAI-compatible provider
- **AND** a backend Codex Responses request includes Computer Use plugin context
- **WHEN** the provider emits a function call for a bridged Computer Use function tool
- **THEN** the client-visible response item uses `namespace = "mcp__computer_use"`
- **AND** the client-visible response item uses the original Computer Use MCP tool name
- **AND** the provider-visible synthetic function-tool name is not forwarded to the client

#### Scenario: Bridged provider request includes Computer Use function tools

- **GIVEN** public model `gpt-5.3-codex` routes backend Codex Responses requests to an OpenAI-compatible provider
- **AND** a backend Codex Responses request includes Computer Use plugin context
- **WHEN** the system opens the provider request
- **THEN** the provider payload includes OpenAI-compatible function tool definitions for Computer Use MCP tools
- **AND** the provider payload includes compatibility instructions that tell the provider to use those functions instead of `resources/list` for Computer Use
