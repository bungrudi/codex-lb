## ADDED Requirements

### Requirement: External model routes do not expose provider model ids in model catalogs

Configured external model routes MUST NOT add provider ids or provider target model ids to public model catalogs. `GET /v1/models` and `GET /backend-api/codex/models` SHALL continue to build their visible model entries from the existing model registry/bootstrap public model data and SHALL use API-key model filtering against public model ids.

#### Scenario: Provider target model is hidden from /v1/models

- **GIVEN** an enabled external route maps public model `gpt-5.3-codex` to provider target model `minimax/minimax-m3`
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response MAY contain public model `gpt-5.3-codex` if the model registry exposes it
- **AND** the response does not contain model id `minimax/minimax-m3`
- **AND** the response does not expose provider id `openrouter`

#### Scenario: Provider target model is hidden from Codex-native model catalog

- **GIVEN** an enabled external route maps public model `gpt-5.3-codex` to provider target model `minimax/minimax-m3`
- **WHEN** a client calls `GET /backend-api/codex/models`
- **THEN** the response is built from public Codex model metadata
- **AND** the response does not contain model id `minimax/minimax-m3`

#### Scenario: API key model filtering remains public-model based

- **GIVEN** an API key allows only `gpt-5.3-codex`
- **AND** `gpt-5.3-codex` is externally routed to `minimax/minimax-m3`
- **WHEN** the key calls `GET /v1/models`
- **THEN** filtering evaluates public model `gpt-5.3-codex`
- **AND** no provider target model id is returned
