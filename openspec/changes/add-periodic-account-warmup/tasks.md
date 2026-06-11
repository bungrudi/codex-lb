## 1. OpenSpec artifacts

- [x] 1.1 Create proposal, specs, context, and design artifacts for periodic account warm-up.
- [x] 1.2 Resolve design constants before implementation: scheduler tick interval is fixed 1 hour and stale pending-attempt timeout is fixed 30 minutes.

## 2. Data model and migrations

- [x] 2.1 Add periodic warm-up settings to `dashboard_settings` with disabled/backfilled defaults: enabled, interval hours, model, prompt, and target scope.
- [x] 2.2 Add per-account periodic warm-up opt-in state to `accounts` with default `false`.
- [x] 2.3 Add periodic warm-up attempt persistence with account id, unique claim key, status, model, attempted/completed timestamps, request id, and error fields.
- [x] 2.4 Add indexes/constraints that support latest-attempt lookup and atomic duplicate-claim prevention.
- [x] 2.5 Add Alembic migration coverage for fresh databases and existing installs, including disabled-by-default backfill behavior.

## 3. Backend settings and account surfaces

- [x] 3.1 Extend settings ORM/repository/service/API schemas with periodic warm-up fields and validation.
- [x] 3.2 Extend frontend-facing settings payloads to expose periodic warm-up fields in camelCase.
- [x] 3.3 Add account repository/service/API support for periodic warm-up opt-in toggling when target scope is `account_opt_in`.
- [x] 3.4 Extend account summary schemas/mappers to include `periodicWarmupEnabled` and latest periodic warm-up attempt status.

## 4. Periodic warm-up backend flow

- [x] 4.1 Extract or share the existing minimal warm-up sender logic so periodic warm-up can reuse auth refresh, upstream proxy routing, stream timeout bounds, usage extraction, and safe request construction.
- [x] 4.2 Implement a periodic warm-up repository for latest-attempt lookup, due-account claim insertion, completion updates, and stale pending cleanup.
- [x] 4.3 Implement `PeriodicWarmupService` target selection for `all_active` and `account_opt_in` scopes, skipping unsafe account states.
- [x] 4.4 Implement per-account due-time evaluation from persisted latest attempt timestamps.
- [x] 4.5 Implement bounded concurrent periodic warm-up submission and durable success/failure attempt completion.
- [x] 4.6 Record request-log rows with `request_kind="warmup"`, `source="periodic_warmup"`, account plan snapshot, and upstream proxy route metadata where available.
- [x] 4.7 Ensure diagnostics avoid raw tokens, API keys, and full prompt content.

## 5. Scheduler integration

- [x] 5.1 Add `PeriodicAccountWarmupScheduler` using existing background-session, leader-election, stop/cancel, and in-process lock patterns.
- [x] 5.2 Wire the scheduler into FastAPI lifespan startup/shutdown.
- [x] 5.3 Ensure disabled settings cause scheduler ticks to return without loading or sending account warm-ups.
- [x] 5.4 Ensure stale pending claims are marked failed after the selected timeout so abandoned work does not remain pending indefinitely.

## 6. Dashboard UI

- [x] 6.1 Extend settings Zod schemas, update request builder, and settings hooks for periodic warm-up fields.
- [x] 6.2 Add Settings page controls for enabled state, interval hours, model, prompt, and target scope.
- [x] 6.3 Add frontend validation that blocks blank model/prompt and interval values below one whole hour.
- [x] 6.4 Show latest periodic warm-up attempt status in account list/detail/dashboard account-card surfaces when provided.
- [x] 6.5 Add accessible per-account periodic warm-up opt-in controls when target scope is `account_opt_in`.

## 7. Tests

- [x] 7.1 Add migration/schema tests for new settings columns, account opt-in column, attempt table, indexes, and defaults.
- [x] 7.2 Add settings API tests for valid updates, disabled defaults, and invalid interval/model/prompt/scope rejection.
- [x] 7.3 Add account API/mapping tests for opt-in toggling and latest periodic warm-up status exposure.
- [x] 7.4 Add service unit tests for due-time evaluation, target scope behavior, unsafe-state skips, and no-previous-attempt behavior.
- [x] 7.5 Add concurrency/deduplication tests proving two workers cannot submit duplicate warm-ups for the same due account.
- [x] 7.6 Add request-log tests proving periodic warm-up rows are tagged as warm-up with `source="periodic_warmup"` and excluded from existing aggregate accounting paths.
- [x] 7.7 Add scheduler tests for disabled no-op, leader-election skip, enabled run, stale pending cleanup, and shutdown cancellation.
- [x] 7.8 Add frontend tests for settings controls, validation, account status display, and accessible opt-in controls.

## 8. Validation

- [x] 8.1 Run targeted backend tests for periodic warm-up service, scheduler, settings, account API, migrations, and request-log accounting.
- [x] 8.2 Run targeted frontend tests for settings/account surfaces.
- [x] 8.3 Run lint/type checks for touched backend and frontend files.
- [x] 8.4 Run OpenSpec validation for the change and specs.
