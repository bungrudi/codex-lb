from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.core.utils.time import utcnow
from app.db.models import Account, AccountPeriodicWarmup, AccountStatus, DashboardSettings
from app.modules.limit_warmup.service import LimitWarmupSender, LimitWarmupSendResult, resolve_warmup_model
from app.modules.request_logs.repository import RequestLogsRepository

from .repository import PeriodicWarmupRepository

logger = logging.getLogger(__name__)

PERIODIC_WARMUP_SOURCE = "periodic_warmup"
PERIODIC_WARMUP_REQUEST_KIND = "warmup"
PERIODIC_WARMUP_TICK_INTERVAL_SECONDS = 3600
PERIODIC_WARMUP_STALE_PENDING_SECONDS = 1800
_PERIODIC_WARMUP_MAX_CONCURRENT_SENDS = 4
_SAFE_TARGET_STATUSES = frozenset({AccountStatus.ACTIVE})
_TARGET_SCOPES = frozenset({"all_active", "account_opt_in"})


@dataclass(frozen=True, slots=True)
class PeriodicWarmupSendOutcome:
    attempt: AccountPeriodicWarmup
    account: Account
    model: str
    result: LimitWarmupSendResult | None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PeriodicWarmupRunSummary:
    checked_accounts: int
    claimed_accounts: int
    submitted_accounts: int
    failed_accounts: int
    skipped_accounts: int
    stale_pending_marked: int


class PeriodicWarmupAccountsRepository(Protocol):
    async def list_accounts(self, *, refresh_existing: bool = False) -> list[Account]: ...


class PeriodicWarmupService:
    def __init__(
        self,
        attempts_repo: PeriodicWarmupRepository,
        request_logs_repo: RequestLogsRepository,
        *,
        sender: LimitWarmupSender,
    ) -> None:
        self._attempts_repo = attempts_repo
        self._request_logs_repo = request_logs_repo
        self._sender = sender

    async def run_for_settings(
        self,
        *,
        accounts: list[Account],
        settings: DashboardSettings,
    ) -> PeriodicWarmupRunSummary:
        now = utcnow()
        stale_pending_marked = await self._attempts_repo.mark_stale_pending(
            cutoff=now - timedelta(seconds=PERIODIC_WARMUP_STALE_PENDING_SECONDS),
            completed_at=now,
        )
        if not settings.periodic_warmup_enabled:
            return PeriodicWarmupRunSummary(
                checked_accounts=0,
                claimed_accounts=0,
                submitted_accounts=0,
                failed_accounts=0,
                skipped_accounts=0,
                stale_pending_marked=stale_pending_marked,
            )

        target_accounts = _target_accounts(accounts, target_scope=settings.periodic_warmup_target_scope)
        account_ids = [account.id for account in target_accounts]
        latest_attempts = await self._attempts_repo.latest_by_account(account_ids)
        interval = timedelta(hours=settings.periodic_warmup_interval_hours)
        due_accounts = [
            account
            for account in target_accounts
            if _account_is_due(latest_attempts.get(account.id), now=now, interval=interval)
        ]
        skipped_accounts = len(target_accounts) - len(due_accounts)
        send_tasks: dict[asyncio.Task[PeriodicWarmupSendOutcome], AccountPeriodicWarmup] = {}
        send_semaphore = asyncio.Semaphore(_PERIODIC_WARMUP_MAX_CONCURRENT_SENDS)
        claimed_accounts = 0

        for account in due_accounts:
            model = resolve_warmup_model(settings.periodic_warmup_model, account)
            claim_key = _claim_key(account.id, latest_attempts.get(account.id))
            attempt = await self._attempts_repo.try_create_claim(
                account_id=account.id,
                claim_key=claim_key,
                model=model or settings.periodic_warmup_model,
                attempted_at=now,
            )
            if attempt is None:
                skipped_accounts += 1
                continue
            claimed_accounts += 1
            if model is None:
                await self._attempts_repo.complete_attempt(
                    attempt.id,
                    status="skipped",
                    completed_at=utcnow(),
                    error_code="model_unavailable",
                    error_message="No eligible priced text model was available for periodic warm-up",
                )
                skipped_accounts += 1
                continue
            send_task = asyncio.create_task(
                self._send_warmup(
                    attempt,
                    account=account,
                    model=model,
                    prompt=settings.periodic_warmup_prompt,
                    semaphore=send_semaphore,
                ),
                name=f"periodic-warmup:{attempt.id}",
            )
            send_tasks[send_task] = attempt

        submitted_accounts = 0
        failed_accounts = 0
        pending_send_tasks = set(send_tasks)
        try:
            while pending_send_tasks:
                completed_send_tasks, pending_send_tasks = await asyncio.wait(
                    pending_send_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for send_task in completed_send_tasks:
                    outcome = await send_task
                    completed = await self._complete_warmup(outcome)
                    if completed is not None and completed.status == "succeeded":
                        submitted_accounts += 1
                    else:
                        failed_accounts += 1
        finally:
            if pending_send_tasks:
                for send_task in pending_send_tasks:
                    send_task.cancel()
                drained_results = await asyncio.gather(*pending_send_tasks, return_exceptions=True)
                for send_task, drained_result in zip(pending_send_tasks, drained_results, strict=True):
                    if isinstance(drained_result, PeriodicWarmupSendOutcome):
                        completed = await self._complete_warmup(drained_result)
                        if completed is not None and completed.status == "succeeded":
                            submitted_accounts += 1
                        else:
                            failed_accounts += 1
                        continue
                    await self._attempts_repo.complete_attempt(
                        send_tasks[send_task].id,
                        status="failed",
                        completed_at=utcnow(),
                        error_code="warmup_cancelled"
                        if isinstance(drained_result, asyncio.CancelledError)
                        else "warmup_send_failed",
                        error_message="Periodic warm-up was cancelled during shutdown"
                        if isinstance(drained_result, asyncio.CancelledError)
                        else _truncate(str(drained_result)) or "Periodic warm-up send failed",
                    )
                    failed_accounts += 1

        return PeriodicWarmupRunSummary(
            checked_accounts=len(target_accounts),
            claimed_accounts=claimed_accounts,
            submitted_accounts=submitted_accounts,
            failed_accounts=failed_accounts,
            skipped_accounts=skipped_accounts,
            stale_pending_marked=stale_pending_marked,
        )

    async def _send_warmup(
        self,
        attempt: AccountPeriodicWarmup,
        *,
        account: Account,
        model: str,
        prompt: str,
        semaphore: asyncio.Semaphore,
    ) -> PeriodicWarmupSendOutcome:
        try:
            async with semaphore:
                result = await self._sender.send(account, model=model, prompt=prompt)
        except Exception as exc:
            logger.warning("Periodic warm-up send failed account_id=%s", account.id, exc_info=True)
            return PeriodicWarmupSendOutcome(
                attempt=attempt,
                account=account,
                model=model,
                result=None,
                error_message=str(exc),
            )
        return PeriodicWarmupSendOutcome(attempt=attempt, account=account, model=model, result=result)

    async def _complete_warmup(self, outcome: PeriodicWarmupSendOutcome) -> AccountPeriodicWarmup | None:
        if outcome.result is None:
            return await self._attempts_repo.complete_attempt(
                outcome.attempt.id,
                status="failed",
                completed_at=utcnow(),
                error_code="warmup_send_failed",
                error_message=_truncate(outcome.error_message),
            )

        result = outcome.result
        await self._record_request_log(account=outcome.account, model=outcome.model, result=result)
        return await self._attempts_repo.complete_attempt(
            outcome.attempt.id,
            status="succeeded" if result.success else "failed",
            completed_at=utcnow(),
            request_id=result.request_id,
            error_code=result.error_code,
            error_message=_truncate(result.error_message),
        )

    async def _record_request_log(
        self,
        *,
        account: Account,
        model: str,
        result: LimitWarmupSendResult,
    ) -> None:
        usage = result.usage
        input_tokens = usage.input_tokens if usage is not None else None
        output_tokens = usage.output_tokens if usage is not None else None
        cached_input_tokens = (
            usage.input_tokens_details.cached_tokens
            if usage is not None and usage.input_tokens_details is not None
            else None
        )
        reasoning_tokens = (
            usage.output_tokens_details.reasoning_tokens
            if usage is not None and usage.output_tokens_details is not None
            else None
        )
        await self._request_logs_repo.add_log(
            account_id=account.id,
            request_id=result.request_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_ms=result.latency_ms,
            status="success" if result.success else "error",
            error_code=result.error_code,
            error_message=_truncate(result.error_message),
            transport="http",
            plan_type=account.plan_type,
            source=PERIODIC_WARMUP_SOURCE,
            request_kind=PERIODIC_WARMUP_REQUEST_KIND,
            upstream_proxy_route_mode=result.upstream_proxy_route_mode,
            upstream_proxy_pool_id=result.upstream_proxy_pool_id,
            upstream_proxy_endpoint_id=result.upstream_proxy_endpoint_id,
            upstream_proxy_fallback_used=result.upstream_proxy_fallback_used,
            upstream_proxy_fail_closed_reason=result.upstream_proxy_fail_closed_reason,
        )


def _target_accounts(accounts: list[Account], *, target_scope: str) -> list[Account]:
    if target_scope not in _TARGET_SCOPES:
        return []
    active_accounts = [account for account in accounts if account.status in _SAFE_TARGET_STATUSES]
    if target_scope == "account_opt_in":
        return [account for account in active_accounts if account.periodic_warmup_enabled]
    return active_accounts


def _account_is_due(attempt: AccountPeriodicWarmup | None, *, now: datetime, interval: timedelta) -> bool:
    if attempt is None:
        return True
    return now - attempt.attempted_at >= interval


def _claim_key(account_id: str, latest_attempt: AccountPeriodicWarmup | None) -> str:
    if latest_attempt is None:
        return f"periodic:{account_id}:initial"
    return f"periodic:{account_id}:after:{latest_attempt.id}"


def _truncate(value: str | None, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."
