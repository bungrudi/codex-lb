from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from app.core.utils.time import utcnow
from app.db.models import Account, AccountPeriodicWarmup, AccountStatus
from app.modules.limit_warmup.service import LimitWarmupSendResult
from app.modules.periodic_warmup.repository import PeriodicWarmupRepository
from app.modules.periodic_warmup.service import PeriodicWarmupService
from app.modules.request_logs.repository import RequestLogsRepository


class FakeAttemptsRepo:
    def __init__(self, latest: dict[str, AccountPeriodicWarmup] | None = None) -> None:
        self.latest = latest or {}
        self.claimed: list[str] = []
        self.completed: dict[int, str] = {}
        self.claim_keys: set[str] = set()
        self._claim_lock = asyncio.Lock()
        self._next_id = 1

    async def latest_by_account(self, account_ids: list[str]) -> dict[str, AccountPeriodicWarmup]:
        return {account_id: self.latest[account_id] for account_id in account_ids if account_id in self.latest}

    async def try_create_claim(self, *, account_id: str, claim_key: str, model: str, attempted_at):
        async with self._claim_lock:
            if claim_key in self.claim_keys:
                return None
            self.claim_keys.add(claim_key)
            self.claimed.append(account_id)
            row = AccountPeriodicWarmup(
                id=self._next_id,
                account_id=account_id,
                claim_key=claim_key,
                status="pending",
                model=model,
                attempted_at=attempted_at,
            )
            self._next_id += 1
            return row

    async def complete_attempt(self, attempt_id: int, *, status: str, completed_at, **_kwargs):
        self.completed[attempt_id] = status
        return AccountPeriodicWarmup(
            id=attempt_id,
            account_id="acc",
            claim_key=f"claim-{attempt_id}",
            status=status,
            model="gpt-5.4-mini",
            attempted_at=completed_at,
            completed_at=completed_at,
        )

    async def mark_stale_pending(self, *, cutoff, completed_at) -> int:
        return 0


class FakeRequestLogsRepo:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def add_log(self, **kwargs):
        self.rows.append(kwargs)
        return object()


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, account: Account, *, model: str, prompt: str) -> LimitWarmupSendResult:
        self.sent.append((account.id, model, prompt))
        return LimitWarmupSendResult(
            request_id=f"periodic-{account.id}",
            success=True,
            latency_ms=12,
        )


def make_account(account_id: str, *, status: AccountStatus = AccountStatus.ACTIVE, opt_in: bool = False) -> Account:
    return Account(
        id=account_id,
        chatgpt_account_id=account_id,
        email=f"{account_id}@example.com",
        plan_type="plus",
        access_token_encrypted=b"access",
        refresh_token_encrypted=b"refresh",
        id_token_encrypted=b"id",
        last_refresh=utcnow(),
        status=status,
        periodic_warmup_enabled=opt_in,
    )


def make_settings(**overrides):
    values = {
        "periodic_warmup_enabled": True,
        "periodic_warmup_interval_hours": 6,
        "periodic_warmup_model": "gpt-5.4-mini",
        "periodic_warmup_prompt": "Say OK.",
        "periodic_warmup_target_scope": "all_active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_periodic_warmup_sends_due_account_without_previous_attempt() -> None:
    attempts = FakeAttemptsRepo()
    request_logs = FakeRequestLogsRepo()
    sender = FakeSender()
    service = PeriodicWarmupService(
        cast(PeriodicWarmupRepository, attempts),
        cast(RequestLogsRepository, request_logs),
        sender=sender,
    )

    summary = await service.run_for_settings(accounts=[make_account("acc-1")], settings=make_settings())

    assert summary.claimed_accounts == 1
    assert summary.submitted_accounts == 1
    assert sender.sent == [("acc-1", "gpt-5.4-mini", "Say OK.")]
    assert request_logs.rows[0]["request_kind"] == "warmup"
    assert request_logs.rows[0]["source"] == "periodic_warmup"


@pytest.mark.asyncio
async def test_periodic_warmup_duplicate_claim_submits_once() -> None:
    attempts = FakeAttemptsRepo()
    request_logs = FakeRequestLogsRepo()
    sender = FakeSender()
    service_a = PeriodicWarmupService(
        cast(PeriodicWarmupRepository, attempts),
        cast(RequestLogsRepository, request_logs),
        sender=sender,
    )
    service_b = PeriodicWarmupService(
        cast(PeriodicWarmupRepository, attempts),
        cast(RequestLogsRepository, request_logs),
        sender=sender,
    )
    account = make_account("acc-1")
    settings = make_settings()

    summary_a, summary_b = await asyncio.gather(
        service_a.run_for_settings(accounts=[account], settings=settings),
        service_b.run_for_settings(accounts=[account], settings=settings),
    )

    assert summary_a.claimed_accounts + summary_b.claimed_accounts == 1
    assert summary_a.submitted_accounts + summary_b.submitted_accounts == 1
    assert sender.sent == [("acc-1", "gpt-5.4-mini", "Say OK.")]
    assert len(request_logs.rows) == 1


@pytest.mark.asyncio
async def test_periodic_warmup_skips_recent_attempt() -> None:
    recent = AccountPeriodicWarmup(
        id=10,
        account_id="acc-1",
        claim_key="periodic:acc-1:initial",
        status="succeeded",
        model="gpt-5.4-mini",
        attempted_at=utcnow() - timedelta(hours=2),
    )
    attempts = FakeAttemptsRepo({"acc-1": recent})
    sender = FakeSender()
    service = PeriodicWarmupService(
        cast(PeriodicWarmupRepository, attempts),
        cast(RequestLogsRepository, FakeRequestLogsRepo()),
        sender=sender,
    )

    summary = await service.run_for_settings(accounts=[make_account("acc-1")], settings=make_settings())

    assert summary.claimed_accounts == 0
    assert summary.skipped_accounts == 1
    assert sender.sent == []


@pytest.mark.asyncio
async def test_periodic_warmup_account_opt_in_scope() -> None:
    attempts = FakeAttemptsRepo()
    sender = FakeSender()
    service = PeriodicWarmupService(
        cast(PeriodicWarmupRepository, attempts),
        cast(RequestLogsRepository, FakeRequestLogsRepo()),
        sender=sender,
    )

    await service.run_for_settings(
        accounts=[make_account("acc-1", opt_in=True), make_account("acc-2", opt_in=False)],
        settings=make_settings(periodic_warmup_target_scope="account_opt_in"),
    )

    assert sender.sent == [("acc-1", "gpt-5.4-mini", "Say OK.")]


@pytest.mark.asyncio
async def test_periodic_warmup_skips_unsafe_states() -> None:
    attempts = FakeAttemptsRepo()
    sender = FakeSender()
    service = PeriodicWarmupService(
        cast(PeriodicWarmupRepository, attempts),
        cast(RequestLogsRepository, FakeRequestLogsRepo()),
        sender=sender,
    )

    await service.run_for_settings(
        accounts=[
            make_account("paused", status=AccountStatus.PAUSED),
            make_account("quota", status=AccountStatus.QUOTA_EXCEEDED),
            make_account("active", status=AccountStatus.ACTIVE),
        ],
        settings=make_settings(),
    )

    assert sender.sent == [("active", "gpt-5.4-mini", "Say OK.")]
