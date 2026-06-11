## Context

`codex-lb` already has two warm-up flows:

1. Manual/API warm-up via `/v1/warmup`, scoped by API key and request mode.
2. Reset-confirmed limit warm-up, triggered by usage refresh after an exhausted window becomes available again.

Periodic account warm-up is a third trigger type. It is not client-initiated and it is not reset-driven. It is a dashboard-configurable background loop that periodically sends one minimal upstream Responses request per due account.

## Goals / Non-Goals

**Goals:**
- Add disabled-by-default periodic warm-up controlled from the dashboard settings API/UI.
- Use per-account due-time scheduling: each account is due from its own latest periodic attempt timestamp.
- Support `all_active` and `account_opt_in` target scopes.
- Reuse the existing safe warm-up sending path where practical: auth refresh, upstream proxy routing, minimal streaming Responses request, bounded concurrency, and request-log insertion.
- Persist attempt history so restarts and multiple replicas do not duplicate due work.
- Keep periodic rows visible in request logs and excluded from aggregate accounting via `request_kind="warmup"`.

**Non-Goals:**
- Add another public `/v1/*` warm-up endpoint.
- Change `/v1/warmup` mode semantics.
- Change reset-confirmed limit warm-up trigger semantics.
- Build a generic background job framework.

## Data Model

Add periodic warm-up fields to `dashboard_settings`:

- `periodic_warmup_enabled` boolean, default `false`.
- `periodic_warmup_interval_hours` integer, default `6`, minimum `1`.
- `periodic_warmup_model` string, default `auto`.
- `periodic_warmup_prompt` text, default `Say OK.`.
- `periodic_warmup_target_scope` string enum, default `all_active`.

Add per-account opt-in state to `accounts`:

- `periodic_warmup_enabled` boolean, default `false`.

Add a periodic attempt table, e.g. `account_periodic_warmups`:

- `id` integer primary key.
- `account_id` foreign key to `accounts` with cascade delete.
- `claim_key` string, unique.
- `status` string: `pending`, `succeeded`, `failed`, or `skipped`.
- `model` string.
- `attempted_at` datetime.
- `completed_at` nullable datetime.
- `request_id` nullable string.
- `error_code` nullable string.
- `error_message` nullable text.
- created/updated timestamps.

The attempt row is both the durable history and the deduplication claim. The unique `claim_key` prevents two workers from claiming the same account/due interval.

## Claim and Due-Time Algorithm

The scheduler computes due accounts from persisted attempts:

```text
latest_attempt = latest periodic attempt for account

if latest_attempt is missing:
    due = true
else:
    due = latest_attempt.attempted_at <= now - interval
```

Claiming uses a stable key derived from the account and the latest attempt that made the account due:

```text
claim_key = "periodic:{account_id}:{latest_attempt.id or initial}"
```

Two workers that race from the same snapshot will compute the same claim key. One insert succeeds; the other receives an integrity conflict and skips sending upstream traffic.

After a claim is inserted with `status="pending"`, the service sends the warm-up request and updates the row to `succeeded` or `failed`. Stale pending rows older than 30 minutes should be marked failed on later scheduler ticks so abandoned claims do not look permanently in progress.

## Scheduler

Add `PeriodicAccountWarmupScheduler`, following existing scheduler patterns:

- starts from `app/main.py` lifespan alongside usage/model/quota schedulers;
- uses existing leader election before each run;
- uses an in-process lock to avoid overlapping ticks within one process;
- reads dashboard settings on every tick;
- returns immediately when disabled;
- runs every fixed 1-hour tick interval, while due-time logic enforces the operator's configured hour interval per account.

The scheduler delegates work to a service rather than sending directly.

```text
PeriodicAccountWarmupScheduler.run_once()
  ├─ acquire leader
  ├─ load settings
  ├─ if disabled: return
  ├─ load accounts + latest attempts
  ├─ claim due accounts
  └─ send claimed warm-ups with bounded concurrency
```

## Service and Sending Path

Add `PeriodicWarmupService` plus a repository for attempt queries/claims/completion.

The service should reuse the existing warm-up sender behavior rather than creating a second upstream request implementation. The cleanest path is to extract the generic pieces from `app/modules/limit_warmup/service.py` into a shared warm-up sender module, while keeping compatibility imports for limit warm-up:

- warm-up send result dataclasses;
- auth refresh and token decrypt flow;
- upstream proxy route resolution;
- minimal streaming Responses request construction;
- bounded stream timeouts;
- usage extraction from terminal stream events.

The periodic service records request logs with:

- `request_kind="warmup"`;
- `source="periodic_warmup"`;
- `transport="http"`;
- account plan type snapshot;
- upstream proxy route metadata when available.

No API-key usage reservation is involved because periodic warm-up is a dashboard-owned internal background action, not an API-key-authenticated client request.

## Model Resolution

`periodic_warmup_model="auto"` should follow the existing limit warm-up resolver: select the cheapest eligible priced text model for the account plan. Any other configured value is used literally after trimming and validation.

This keeps the default safe from a cost perspective while still allowing operators to pin a model that better matches the path they want to keep warm.

## Target Scope

Target selection happens before due-time claiming:

```text
all_active:
  Account.status == ACTIVE

account_opt_in:
  Account.status == ACTIVE
  and Account.periodic_warmup_enabled == true
```

All other statuses are skipped regardless of scope:

- `paused`
- `deactivated`
- `reauth_required`
- `rate_limited`
- `quota_exceeded`

The account object should be loaded fresh during scheduler execution so dashboard opt-in changes are respected without waiting for process restart.

## Settings and Admin API

Extend the existing settings schema/service/repository/API flow with periodic warm-up fields. Backend validation should reject:

- interval below 1 hour;
- non-integer interval values;
- blank model;
- blank prompt;
- unsupported target scope.

Expose account opt-in through account admin APIs only if needed by the selected scope. A simple route mirroring the existing limit warm-up toggle is sufficient:

```text
PUT /api/accounts/{account_id}/periodic-warmup
{ "enabled": true }
```

Account summaries should include:

- `periodicWarmupEnabled`;
- latest periodic warm-up status object when available.

## Dashboard UI

Add a Periodic warm-up block near the existing warm-up controls on the Settings page:

- enable/disable switch;
- interval hours numeric input;
- model input;
- prompt input;
- target scope select (`All active accounts`, `Only opted-in accounts`);
- save button with frontend validation matching backend bounds.

Account views should show latest periodic attempt status when present. If target scope is `account_opt_in`, account list/detail/card surfaces should expose a per-account opt-in toggle with an accessible label that includes the account context.

## Observability and Accounting

Request logs are the primary durable operator surface. Periodic warm-up rows remain visible in request-log lists but excluded from aggregate accounting through the existing `request_kind="warmup"` filter behavior.

The `source="periodic_warmup"` value distinguishes periodic warm-up from:

- manual/API `/v1/warmup`;
- reset-confirmed limit warm-up;
- quota-planner warm-up.

Structured logs should include low-cardinality metadata such as account id, attempt id, status, and error code. They must not include raw tokens, API keys, or full prompt content.

## Failure Modes

- **Auth refresh failure:** mark attempt failed with the refresh error code/message; do not retry until the account is due again by interval policy unless a later design adds retry controls.
- **Upstream quota/rate-limit response:** record failed request log and attempt status; the account may later be marked blocked by existing account health paths if applicable.
- **Process crash after claim:** stale `pending` attempts are marked failed by a later tick after a conservative timeout.
- **Multiple replicas:** leader election prevents most duplicate work, and unique `claim_key` prevents duplicate sends when leader handoff or overlapping ticks race.
- **Operator disables feature mid-run:** in-flight sends may finish and record attempts; subsequent ticks do not claim new work.

## Migration Plan

1. Add dashboard settings columns with disabled/backfilled defaults.
2. Add account opt-in column with default `false`.
3. Add periodic attempt table with unique `claim_key` and account/time indexes.
4. Wire backend settings/account schemas and repository fields.
5. Add scheduler/service/repository and shared warm-up sender extraction.
6. Add frontend settings controls and account status/opt-in surfaces.
7. Validate with backend, migration, and frontend regression tests.

Rollback: because the feature is disabled by default and additive, rolling back application code can leave the added columns/table in place without affecting existing request routing.

## Resolved Constants

- Scheduler tick interval: fixed 1 hour.
- Stale pending-attempt timeout: fixed 30 minutes.
