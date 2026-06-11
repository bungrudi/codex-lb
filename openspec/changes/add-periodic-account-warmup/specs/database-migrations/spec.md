## ADDED Requirements

### Requirement: Periodic warm-up persistence

The database schema SHALL persist periodic warm-up configuration, per-account opt-in state when account opt-in scope is used, and periodic warm-up attempt history. Existing databases SHALL migrate to periodic warm-up disabled with no existing account opted in by default.

#### Scenario: Existing installs remain disabled after migration
- **WHEN** an existing database is migrated
- **THEN** periodic account warm-up is disabled
- **AND** existing accounts are not opted in for account-scoped periodic warm-up by default

#### Scenario: Periodic warm-up settings are persisted
- **WHEN** migrations run to head
- **THEN** the dashboard settings schema can store periodic warm-up enabled state, interval, model, prompt, and target scope

#### Scenario: Periodic warm-up attempt history is persisted
- **WHEN** migrations run to head
- **THEN** the schema can store periodic warm-up attempts with account id, status, model, attempted timestamp, completion timestamp, and error details

### Requirement: Periodic warm-up claim prevents duplicate sends

The database schema or repository update path SHALL support atomic claiming of due periodic warm-up work for an account so overlapping scheduler ticks or multiple replicas cannot submit duplicate requests for the same account and due interval.

#### Scenario: Concurrent workers claim one due account once
- **WHEN** two workers attempt to claim the same due account for periodic warm-up at the same time
- **THEN** at most one claim succeeds
- **AND** at most one upstream periodic warm-up request is sent for that account and due interval
