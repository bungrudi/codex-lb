## ADDED Requirements

### Requirement: API-key policy for external model routes uses public model ids

For externally routed requests, API-key model restrictions, enforced models, service-tier enforcement, model-scoped limit applicability, and request-aware usage reservations MUST evaluate the effective public model id, not the provider target model id. Provider target model ids MUST NOT be accepted as substitutes for public allowlist entries.

When an API key has account-assignment scope enabled, external provider routes SHALL still be eligible because no ChatGPT account is selected; request logs for those provider-routed requests MUST store `account_id = NULL` while preserving the authenticated `api_key_id`.

#### Scenario: Public allowed model permits external route

- **GIVEN** an API key allows model `gpt-5.3-codex`
- **AND** `gpt-5.3-codex` routes externally to provider target model `minimax/minimax-m3`
- **WHEN** the key sends a matching proxy request for `gpt-5.3-codex`
- **THEN** the request is permitted by model restriction enforcement
- **AND** the provider request uses `minimax/minimax-m3`

#### Scenario: Provider target model is not an allowlist substitute

- **GIVEN** an API key allows model `minimax/minimax-m3`
- **AND** public model `gpt-5.3-codex` routes externally to `minimax/minimax-m3`
- **WHEN** the key sends a request for `gpt-5.3-codex`
- **THEN** the request is rejected with OpenAI-format error code `model_not_allowed`
- **AND** no provider request is opened

#### Scenario: Enforced public model can select external route

- **GIVEN** an API key enforces model `gpt-5.3-codex`
- **AND** `gpt-5.3-codex` routes externally for the requested endpoint
- **WHEN** the key sends a request for another public model
- **THEN** the effective public model is `gpt-5.3-codex`
- **AND** the external route for `gpt-5.3-codex` is selected

#### Scenario: Account-scoped API key logs external route without account id

- **GIVEN** an API key has assigned ChatGPT account ids
- **AND** a matching external provider route exists
- **WHEN** the key sends a provider-routed request
- **THEN** the request is eligible for external routing
- **AND** the persisted request log stores the API key id
- **AND** the persisted request log stores `account_id = NULL`

### Requirement: External provider usage settles API-key reservations exactly once

For externally routed requests authenticated with an API key, the system MUST finalize or release any API-key usage reservation exactly once. When the provider response includes usage data, the system MUST map provider usage into the existing input, output, cached-input, reasoning-token, and cost accounting fields when those values are available. When provider usage is unavailable or the request fails before usage is known, the system MUST release the reservation or settle according to the existing request-aware reservation policy without leaving the reservation in a reserved state.

#### Scenario: Provider chat usage finalizes reservation

- **WHEN** an externally routed chat completion finishes with provider usage `prompt_tokens = 100` and `completion_tokens = 50`
- **THEN** the API-key reservation is finalized exactly once with `input_tokens = 100` and `output_tokens = 50`

#### Scenario: Provider Responses usage finalizes reservation

- **WHEN** an externally routed Responses request finishes with provider usage `input_tokens = 100` and `output_tokens = 50`
- **THEN** the API-key reservation is finalized exactly once with `input_tokens = 100` and `output_tokens = 50`

#### Scenario: Missing provider usage does not leak reservation

- **WHEN** an externally routed provider request completes or fails without usage data
- **THEN** the API-key reservation is released or otherwise settled exactly once
- **AND** no reservation remains in a reserved state
