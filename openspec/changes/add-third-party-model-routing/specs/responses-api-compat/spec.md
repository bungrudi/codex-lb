## ADDED Requirements

### Requirement: Responses HTTP routes support explicit external model routes

When an HTTP `/v1/responses` request's effective public model has an enabled external route for endpoint `responses`, the service MUST forward the request to the configured OpenAI-compatible provider Responses endpoint using the provider target model. The service MUST preserve the public `/v1/responses` streaming and non-streaming OpenAI Responses contracts, including OpenAI-compatible error envelopes and public SSE normalization.

For external Responses routes, the service MUST rewrite client-visible response model fields back to the effective public model id. The service MUST bypass ChatGPT account selection, ChatGPT token refresh, ChatGPT account-health mutation, and the ChatGPT HTTP responses bridge for the provider-routed request.

Backend Codex HTTP Responses routes MAY use external provider routing only when the route explicitly enables a backend Codex Responses endpoint; otherwise matching routes MUST fail deterministically with `external_route_endpoint_unsupported` for backend Codex Responses traffic.

#### Scenario: Streaming /v1/responses is routed to provider and hides target model

- **GIVEN** public model `gpt-5.3-codex` routes to provider target model `minimax/minimax-m3` for endpoint `responses`
- **WHEN** a client sends streaming `POST /v1/responses` with model `gpt-5.3-codex`
- **THEN** the provider request uses model `minimax/minimax-m3`
- **AND** the public stream emits OpenAI Responses contract events
- **AND** client-visible response model fields are `gpt-5.3-codex`
- **AND** the stream does not expose `minimax/minimax-m3`

#### Scenario: Non-streaming /v1/responses is routed to provider and hides target model

- **GIVEN** public model `gpt-5.3-codex` routes to provider target model `minimax/minimax-m3` for endpoint `responses`
- **WHEN** a client sends non-streaming `POST /v1/responses` with model `gpt-5.3-codex`
- **THEN** the provider request uses model `minimax/minimax-m3`
- **AND** the collected client response uses public model `gpt-5.3-codex` wherever a model field is present

#### Scenario: Provider-routed Responses bypasses ChatGPT bridge

- **GIVEN** the HTTP responses bridge is enabled
- **AND** public model `gpt-5.3-codex` routes externally for endpoint `responses`
- **WHEN** a matching `/v1/responses` request is handled
- **THEN** the request is not submitted to the ChatGPT HTTP responses bridge
- **AND** no ChatGPT account is selected for the request

### Requirement: External model routes fail explicitly for unsupported Responses surfaces

When a request's effective public model has a configured external route but the requested Responses surface is not enabled for that route, the service MUST return an OpenAI-format error with code `external_route_endpoint_unsupported`. The service MUST NOT silently fall through to ChatGPT account-pool routing for that matched public model and unsupported endpoint unless a future explicit fallback policy allows it.

#### Scenario: Compact unsupported for external route

- **GIVEN** public model `gpt-5.3-codex` has an external route that does not enable `responses.compact`
- **WHEN** a client sends `POST /v1/responses/compact` with model `gpt-5.3-codex`
- **THEN** the service returns an OpenAI-format error with code `external_route_endpoint_unsupported`
- **AND** no ChatGPT compact upstream request is opened

#### Scenario: WebSocket unsupported for external route

- **GIVEN** public model `gpt-5.3-codex` has an external route that does not enable `responses.websocket`
- **WHEN** a websocket client attempts to create a response with model `gpt-5.3-codex`
- **THEN** the service returns or emits a deterministic OpenAI-format unsupported-endpoint error
- **AND** no provider HTTP request is opened unless websocket-to-provider bridging has been explicitly implemented for that route
