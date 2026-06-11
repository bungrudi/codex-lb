from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.periodic_warmup import scheduler as scheduler_module
from app.modules.periodic_warmup.scheduler import PeriodicAccountWarmupScheduler
from app.modules.periodic_warmup.service import PeriodicWarmupRunSummary


class _Leader:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.calls = 0

    async def try_acquire(self) -> bool:
        self.calls += 1
        return self.acquired


@asynccontextmanager
async def _session_context():
    yield object()


@pytest.mark.asyncio
async def test_periodic_warmup_scheduler_skips_when_not_leader(monkeypatch) -> None:
    leader = _Leader(False)
    monkeypatch.setattr(scheduler_module, "_get_leader_election", lambda: leader)

    def fail_session():
        raise AssertionError("scheduler should not open a session without leadership")

    monkeypatch.setattr(scheduler_module, "get_background_session", fail_session)

    await PeriodicAccountWarmupScheduler().run_once()

    assert leader.calls == 1


@pytest.mark.asyncio
async def test_periodic_warmup_scheduler_disabled_tick_marks_stale_without_loading_accounts(monkeypatch) -> None:
    leader = _Leader(True)
    stale_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(scheduler_module, "_get_leader_election", lambda: leader)
    monkeypatch.setattr(scheduler_module, "get_background_session", _session_context)

    class FakeSettingsRepository:
        def __init__(self, _session) -> None:
            pass

        async def get_or_create(self):
            return SimpleNamespace(periodic_warmup_enabled=False)

    class FakeAttemptsRepository:
        def __init__(self, _session) -> None:
            pass

        async def mark_stale_pending(self, *, cutoff, completed_at) -> int:
            stale_calls.append({"cutoff": cutoff, "completed_at": completed_at})
            return 2

    class FakeAccountsRepository:
        def __init__(self, _session) -> None:
            pass

        async def list_accounts(self, *, refresh_existing: bool = False):
            raise AssertionError("disabled scheduler tick should not load accounts")

    monkeypatch.setattr(scheduler_module, "SettingsRepository", FakeSettingsRepository)
    monkeypatch.setattr(scheduler_module, "PeriodicWarmupRepository", FakeAttemptsRepository)
    monkeypatch.setattr(scheduler_module, "AccountsRepository", FakeAccountsRepository)

    await PeriodicAccountWarmupScheduler().run_once()

    assert leader.calls == 1
    assert len(stale_calls) == 1
    assert stale_calls[0]["cutoff"] < stale_calls[0]["completed_at"]


@pytest.mark.asyncio
async def test_periodic_warmup_scheduler_enabled_tick_runs_service(monkeypatch) -> None:
    leader = _Leader(True)
    account = SimpleNamespace(id="acc-1")
    service_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(scheduler_module, "_get_leader_election", lambda: leader)
    monkeypatch.setattr(scheduler_module, "get_background_session", _session_context)

    class FakeSettingsRepository:
        def __init__(self, _session) -> None:
            pass

        async def get_or_create(self):
            return SimpleNamespace(periodic_warmup_enabled=True)

    class FakeAttemptsRepository:
        def __init__(self, _session) -> None:
            pass

    class FakeRequestLogsRepository:
        def __init__(self, _session) -> None:
            pass

    class FakeAccountsRepository:
        def __init__(self, _session) -> None:
            self.session = _session

        async def list_accounts(self, *, refresh_existing: bool = False):
            assert refresh_existing is True
            return [account]

    class FakeSender:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class FakeService:
        def __init__(self, attempts_repo, request_logs_repo, *, sender) -> None:
            self.attempts_repo = attempts_repo
            self.request_logs_repo = request_logs_repo
            self.sender = sender

        async def run_for_settings(self, *, accounts, settings):
            service_calls.append({"accounts": accounts, "settings": settings})
            return PeriodicWarmupRunSummary(
                checked_accounts=1,
                claimed_accounts=1,
                submitted_accounts=1,
                failed_accounts=0,
                skipped_accounts=0,
                stale_pending_marked=0,
            )

    monkeypatch.setattr(scheduler_module, "SettingsRepository", FakeSettingsRepository)
    monkeypatch.setattr(scheduler_module, "PeriodicWarmupRepository", FakeAttemptsRepository)
    monkeypatch.setattr(scheduler_module, "RequestLogsRepository", FakeRequestLogsRepository)
    monkeypatch.setattr(scheduler_module, "AccountsRepository", FakeAccountsRepository)
    monkeypatch.setattr(scheduler_module, "StreamingLimitWarmupSender", FakeSender)
    monkeypatch.setattr(scheduler_module, "PeriodicWarmupService", FakeService)

    await PeriodicAccountWarmupScheduler().run_once()

    assert leader.calls == 1
    assert len(service_calls) == 1
    assert service_calls[0]["accounts"] == [account]
    assert service_calls[0]["settings"].periodic_warmup_enabled is True


@pytest.mark.asyncio
async def test_periodic_warmup_scheduler_stop_cancels_running_loop() -> None:
    started = asyncio.Event()

    class BlockingScheduler(PeriodicAccountWarmupScheduler):
        async def run_once(self) -> None:
            started.set()
            await asyncio.sleep(3600)

    scheduler = BlockingScheduler(interval_seconds=3600)

    await scheduler.start()
    await asyncio.wait_for(started.wait(), timeout=1)
    await scheduler.stop()

    assert scheduler._task is None
