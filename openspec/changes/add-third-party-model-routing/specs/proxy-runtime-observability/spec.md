## ADDED Requirements

### Requirement: External model routing emits operator-visible diagnostics

When an external model route is resolved, completed, failed, or falls back, the system MUST emit operator-visible diagnostics that include request id, endpoint family, public model id, provider id, provider target model id, provider status or error code when available, latency when available, and fallback reason when fallback occurs. Diagnostics MUST avoid raw prompt text, raw API keys, credential-bearing provider headers, and unbounded-cardinality labels.

Persisted request logs for external provider traffic MUST keep `model` equal to the public model id and MUST record internal provider metadata sufficient to distinguish provider-routed traffic from ChatGPT account-pool traffic.

#### Scenario: External route resolution is logged

- **WHEN** a request for public model `gpt-5.3-codex` resolves to provider `openrouter` target model `minimax/minimax-m3`
- **THEN** operator diagnostics include the request id, endpoint family, public model id, provider id, and target model id
- **AND** diagnostics do not include raw prompt text or provider API-key values

#### Scenario: External provider request log stores public and internal route identity

- **WHEN** an external provider request completes
- **THEN** the persisted request log stores the public model id in the existing model field
- **AND** the persisted request log records the provider id and provider target model id in internal metadata fields
- **AND** `account_id` is NULL because no ChatGPT account was selected

#### Scenario: Provider failures are distinguishable from ChatGPT account failures

- **WHEN** an external provider returns an error
- **THEN** diagnostics classify the error as an external provider failure
- **AND** diagnostics do not report the failure as a ChatGPT account selection, refresh, quota, or account-health failure

### Requirement: External provider metrics use low-cardinality labels

When metrics are enabled, the system SHALL expose low-cardinality counters or histograms for external provider request totals, latency, errors, token totals, and fallback totals. Metric labels MUST NOT contain raw prompt data, API keys, full URLs with query strings, or unbounded user-controlled strings.

#### Scenario: External route metrics are emitted

- **WHEN** an external provider request completes
- **THEN** metrics record request count and latency with bounded labels such as provider id, endpoint family, and status class
- **AND** metrics do not label by raw prompt, API key, or full request payload

#### Scenario: External fallback metric records reason

- **WHEN** an external route explicitly falls back to the ChatGPT account pool
- **THEN** metrics record a fallback counter with provider id, endpoint family, and low-cardinality fallback reason
