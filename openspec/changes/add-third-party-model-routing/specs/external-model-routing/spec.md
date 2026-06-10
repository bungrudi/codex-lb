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
