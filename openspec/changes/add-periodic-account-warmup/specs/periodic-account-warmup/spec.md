## ADDED Requirements

### Requirement: Periodic account warm-up is configurable and disabled by default

The system SHALL support a periodic account warm-up mechanism that is disabled by default. Operators SHALL be able to configure whether periodic warm-up is enabled, the warm-up interval in whole hours, the model, the prompt, and the target scope. The warm-up interval MUST be at least one hour. Blank model and prompt values MUST be rejected.

#### Scenario: Existing installs do not send periodic warm-up traffic
- **WHEN** an existing deployment is upgraded
- **THEN** periodic account warm-up remains disabled unless an operator explicitly enables it

#### Scenario: Operator enables periodic warm-up
- **WHEN** an operator enables periodic account warm-up with a valid interval, model, prompt, and target scope
- **THEN** subsequent scheduler ticks evaluate due accounts using those persisted settings

#### Scenario: Invalid periodic warm-up interval is rejected
- **WHEN** an operator attempts to save a periodic warm-up interval below one hour or a non-integer hour value
- **THEN** the settings update is rejected

### Requirement: Periodic warm-up uses per-account due-time scheduling

When periodic account warm-up is enabled, the scheduler SHALL evaluate each target account independently. An account SHALL be due only when it has no prior periodic warm-up attempt or its latest periodic warm-up attempt is older than the configured interval. The scheduler SHALL NOT warm an account more than once per configured interval solely because the scheduler ticks multiple times.

#### Scenario: Account with stale last attempt is due
- **GIVEN** periodic account warm-up is enabled with interval `6` hours
- **AND** an active target account's latest periodic warm-up attempt was recorded more than 6 hours ago
- **WHEN** the scheduler runs
- **THEN** the account is eligible for one periodic warm-up attempt

#### Scenario: Account warmed recently is skipped
- **GIVEN** periodic account warm-up is enabled with interval `6` hours
- **AND** an active target account's latest periodic warm-up attempt was recorded 2 hours ago
- **WHEN** the scheduler runs
- **THEN** no upstream warm-up request is sent for that account

#### Scenario: Account with no previous attempt is due
- **GIVEN** periodic account warm-up is enabled
- **AND** an active target account has no prior periodic warm-up attempt
- **WHEN** the scheduler runs
- **THEN** the account is eligible for one periodic warm-up attempt

### Requirement: Periodic warm-up target scope is deterministic

Periodic account warm-up SHALL support an operator-configured target scope. The `all_active` scope SHALL consider every active account. The `account_opt_in` scope SHALL consider only active accounts whose persisted periodic warm-up opt-in is enabled. In all scopes, accounts that are paused, deactivated, reauth-required, rate-limited, or quota-exceeded SHALL NOT receive periodic warm-up traffic.

#### Scenario: All-active scope considers active accounts
- **GIVEN** periodic account warm-up target scope is `all_active`
- **AND** one account is active and one account is paused
- **WHEN** the scheduler evaluates targets
- **THEN** the active account is considered
- **AND** the paused account is skipped

#### Scenario: Account opt-in scope considers only opted-in accounts
- **GIVEN** periodic account warm-up target scope is `account_opt_in`
- **AND** two active accounts exist
- **AND** only one account has periodic warm-up opt-in enabled
- **WHEN** the scheduler evaluates targets
- **THEN** only the opted-in account is considered

#### Scenario: Unsafe account states are skipped
- **WHEN** a target account is paused, deactivated, reauth-required, rate-limited, or quota-exceeded
- **THEN** the scheduler does not send periodic warm-up traffic for that account

### Requirement: Periodic warm-up sends minimal upstream Responses requests

For each due account selected for periodic warm-up, the system SHALL send a minimal upstream Responses request using the configured model and prompt. The request SHALL set `store=false` and SHALL bound output size to a tiny response suitable for warm-up. Periodic warm-up submissions SHALL be concurrency-bounded so a large account pool does not create unbounded upstream fan-out.

#### Scenario: Due account receives minimal warm-up request
- **GIVEN** an active target account is due for periodic warm-up
- **WHEN** the scheduler submits the warm-up
- **THEN** the upstream request uses the configured model and prompt
- **AND** the request is marked `store=false`
- **AND** the output budget is bounded for a minimal response

#### Scenario: Periodic warm-up fan-out is bounded
- **GIVEN** more due accounts exist than the warm-up concurrency limit
- **WHEN** the scheduler submits periodic warm-up requests
- **THEN** no more than the configured or hard-coded concurrency limit are in flight at once

### Requirement: Periodic warm-up attempts are durable and deduplicated

The system SHALL durably record periodic warm-up attempts with account id, status, model, attempted time, completion time when available, and error details when available. The scheduler SHALL atomically claim due account work so multiple replicas or overlapping ticks do not submit duplicate periodic warm-up requests for the same account and due interval.

#### Scenario: Attempt result is recorded
- **WHEN** a periodic warm-up request succeeds or fails for an account
- **THEN** the system records the attempt status, model, attempted timestamp, completion timestamp, and error details when applicable

#### Scenario: Multiple schedulers do not duplicate a due account
- **WHEN** two scheduler workers evaluate the same due account concurrently
- **THEN** at most one worker claims and submits the periodic warm-up request for that due interval

#### Scenario: Restart preserves due-time state
- **GIVEN** an account was warmed recently
- **AND** codex-lb restarts before the configured interval elapses
- **WHEN** the scheduler starts again
- **THEN** it uses the persisted attempt history to skip that account until it is due again
