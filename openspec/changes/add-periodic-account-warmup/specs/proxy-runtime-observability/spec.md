## ADDED Requirements

### Requirement: Periodic warm-up attempts are observable as warm-up traffic

Periodic account warm-up attempts SHALL be recorded in request logs as warm-up traffic with a source that distinguishes them from user requests, manual `/v1/warmup` executions, and reset-confirmed limit warm-up. Periodic warm-up rows SHALL remain visible in request-log views while remaining excluded from aggregate request, error, token, and cost metrics that intentionally exclude warm-up traffic.

#### Scenario: Periodic warm-up request log is identifiable
- **WHEN** a periodic account warm-up request is submitted for an account
- **THEN** the resulting request-log row is marked with warm-up request kind
- **AND** it includes a source value identifying periodic account warm-up

#### Scenario: Periodic warm-up rows do not pollute aggregates
- **WHEN** dashboard aggregate metrics are computed for a time range containing normal requests and periodic warm-up rows
- **THEN** periodic warm-up rows do not contribute to aggregate request, error, token, or cost totals

#### Scenario: Periodic warm-up diagnostics avoid sensitive payloads
- **WHEN** periodic account warm-up logs diagnostics or request-log metadata
- **THEN** diagnostics do not expose account tokens, API keys, or full prompt content
