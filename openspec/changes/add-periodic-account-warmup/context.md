## Context

This change is separate from two existing warm-up paths:

- Manual/API warm-up (`POST /v1/warmup`) warms an API-key-scoped account pool on demand.
- Reset-confirmed limit warm-up sends one small request after usage refresh proves a previously exhausted window has reset.

Periodic account warm-up is time-based. It lets an operator keep account paths exercised during idle periods by sending a small message to due accounts every configured number of hours.

## Decisions

- Use per-account due-time scheduling rather than a single global batch clock. Each account is due based on its own latest periodic warm-up attempt.
- Keep the feature disabled by default because it consumes upstream quota, even if the request is tiny.
- Keep request logs tagged as warm-up traffic so existing warm-up accounting exclusions can continue to apply.
- Keep periodic warm-up settings separate from reset-confirmed limit warm-up settings so enabling one mechanism does not implicitly enable the other.

## Constraints

- Periodic warm-up must not send traffic for unsafe account states such as paused, deactivated, reauth-required, rate-limited, or quota-exceeded.
- Multi-replica deployments need atomic due-account claiming, not just in-memory locks.
- Diagnostics must avoid account tokens, API keys, and full prompt content.

## Example

With interval `6` hours:

```text
Account A last periodic warm-up at 10:00 -> due at 16:00
Account B last periodic warm-up at 10:23 -> due at 16:23
Account C never warmed                  -> due on next scheduler tick
```

If the scheduler ticks at 16:05, Account A and Account C may be claimed and warmed; Account B is skipped until at least 16:23.
