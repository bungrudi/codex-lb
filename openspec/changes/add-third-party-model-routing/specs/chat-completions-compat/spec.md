## ADDED Requirements

### Requirement: Chat Completions supports exact external model routes

When a `/v1/chat/completions` request's effective public model has an enabled external route for endpoint `chat.completions`, the service MUST forward the request to the configured OpenAI-compatible provider `/chat/completions` endpoint using the provider target model. The service MUST preserve existing Chat Completions request validation, message/tool normalization, strict function-tool schema validation, provider-specific thinking alias normalization, OpenAI-compatible error envelopes, streaming chunk contract, and non-streaming response contract.

The service MUST rewrite client-visible `model` fields in provider chat completion responses and streaming chunks back to the effective public model id. A matching external route MUST bypass ChatGPT account selection and MUST NOT require any ChatGPT account to exist.

#### Scenario: Non-streaming chat completion is routed to provider and hides target model

- **GIVEN** public model `gpt-5.3-codex` routes to provider target model `minimax/minimax-m3` for endpoint `chat.completions`
- **WHEN** a client sends a non-streaming `/v1/chat/completions` request with model `gpt-5.3-codex`
- **THEN** the provider request uses model `minimax/minimax-m3`
- **AND** the client response is a `chat.completion` object with `model: "gpt-5.3-codex"`
- **AND** the client response does not expose `minimax/minimax-m3`

#### Scenario: Streaming chat completion preserves chunk contract

- **GIVEN** public model `gpt-5.3-codex` routes to provider target model `minimax/minimax-m3` for endpoint `chat.completions`
- **WHEN** a client sends a streaming `/v1/chat/completions` request with model `gpt-5.3-codex`
- **THEN** the response media type is `text/event-stream`
- **AND** forwarded chunks have object `chat.completion.chunk`
- **AND** forwarded chunk model fields are `gpt-5.3-codex`
- **AND** the stream terminates with `data: [DONE]`

#### Scenario: Existing chat validation still runs before provider request

- **WHEN** a client sends a chat request with an invalid strict function-tool schema for an externally routed model
- **THEN** the service returns the existing OpenAI-compatible 400 `invalid_function_parameters` response
- **AND** no provider request is opened

#### Scenario: External chat route does not require ChatGPT accounts

- **GIVEN** no ChatGPT accounts are configured
- **AND** an enabled external route exists for public model `gpt-5.3-codex` and endpoint `chat.completions`
- **WHEN** a client sends a matching `/v1/chat/completions` request
- **THEN** the request is sent to the external provider
- **AND** the response is not a `no_accounts` error
