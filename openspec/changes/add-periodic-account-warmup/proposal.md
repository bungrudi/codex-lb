## Why

Operators want codex-lb to proactively keep ChatGPT account paths warm without manually calling `/v1/warmup` or waiting for reset-confirmed limit warm-up events. Today, warm-up behavior is either request-triggered by an external client or tied to quota reset detection. There is no dashboard-configurable way to say "send a tiny message to each safe account every X hours" so the account pool stays periodically exercised during idle periods.

This change adds an operator-controlled periodic account warm-up loop with per-account due-time semantics: an account becomes due when its own last periodic warm-up attempt is older than the configured interval. This avoids a single global batch schedule becoming the source of repeated synchronized bursts.

## What Changes

- Add an optional periodic account warm-up mechanism, disabled by default.
- Add dashboard settings for enabling periodic warm-up, configuring the interval in hours, selecting the warm-up model/prompt, and choosing target scope.
- Use per-account due-time scheduling: each eligible account is warmed at most once per configured interval based on that account's last periodic warm-up attempt.
- Send only minimal upstream Responses requests and only for safe account states; paused, deactivated, reauth-required, rate-limited, and quota-exceeded accounts are skipped.
- Record each periodic warm-up attempt durably so restarts and multiple replicas do not duplicate work.
- Mark periodic warm-up request-log rows as warm-up traffic so existing dashboard/API-key aggregate exclusions continue to apply.
- Surface recent periodic warm-up status in dashboard account views or settings feedback so operators can see when accounts were last attempted.

## Capabilities

### New Capabilities

- `periodic-account-warmup`: Dashboard-configurable background scheduler that sends minimal warm-up messages to due, safe accounts every configured interval.

### Modified Capabilities

- `frontend-architecture`: Expose periodic warm-up controls in Settings and recent per-account warm-up status in account-facing dashboard views.
- `database-migrations`: Add persistent settings and attempt/status storage needed for per-account due-time scheduling and deduplication.
- `proxy-runtime-observability`: Ensure periodic warm-up attempts remain visible as warm-up request-log rows without polluting aggregate request/error/cost metrics.

## Impact

- Backend: add scheduler/service/repository flow, guarded by existing leader-election patterns for multi-replica deployments.
- Settings: add persisted periodic warm-up configuration with safe defaults and validation for interval/model/prompt/target scope.
- Dashboard: add GUI controls for the new settings and display recent periodic warm-up status.
- Database: add migration(s) for periodic warm-up settings and durable per-account attempt tracking, or extend existing warm-up attempt storage if that is cleaner.
- Tests: cover scheduler due-time behavior, safety skips, deduplication, request-log warm-up tagging, settings API validation, and dashboard control behavior.
