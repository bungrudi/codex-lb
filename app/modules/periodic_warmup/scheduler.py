from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import AsyncIterator, Protocol, cast

from app.core.utils.time import utcnow
from app.db.session import get_background_session
from app.modules.accounts.repository import AccountsRepository
from app.modules.limit_warmup.service import StreamingLimitWarmupSender
from app.modules.periodic_warmup.repository import PeriodicWarmupRepository
from app.modules.periodic_warmup.service import (
    PERIODIC_WARMUP_STALE_PENDING_SECONDS,
    PERIODIC_WARMUP_TICK_INTERVAL_SECONDS,
    PeriodicWarmupService,
)
from app.modules.request_logs.repository import RequestLogsRepository
from app.modules.settings.repository import SettingsRepository

logger = logging.getLogger(__name__)


class _LeaderElectionLike(Protocol):
    async def try_acquire(self) -> bool: ...


def _get_leader_election() -> _LeaderElectionLike:
    module = importlib.import_module("app.core.scheduling.leader_election")
    return cast(_LeaderElectionLike, module.get_leader_election())


@dataclass(slots=True)
class PeriodicAccountWarmupScheduler:
    interval_seconds: int = PERIODIC_WARMUP_TICK_INTERVAL_SECONDS
    enabled: bool = True
    _task: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        if not self.enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def run_once(self) -> None:
        if not await _get_leader_election().try_acquire():
            return
        async with self._lock:
            try:
                async with get_background_session() as session:
                    settings_repo = SettingsRepository(session)
                    settings = await settings_repo.get_or_create()
                    attempts_repo = PeriodicWarmupRepository(session)
                    request_logs_repo = RequestLogsRepository(session)
                    accounts_repo = AccountsRepository(session)
                    if not settings.periodic_warmup_enabled:
                        now = utcnow()
                        await attempts_repo.mark_stale_pending(
                            cutoff=now - timedelta(seconds=PERIODIC_WARMUP_STALE_PENDING_SECONDS),
                            completed_at=now,
                        )
                        return
                    accounts = await accounts_repo.list_accounts(refresh_existing=True)
                    service = PeriodicWarmupService(
                        attempts_repo,
                        request_logs_repo,
                        sender=StreamingLimitWarmupSender(
                            accounts_repo,
                            accounts_repo_factory=_background_accounts_repo,
                        ),
                    )
                    summary = await service.run_for_settings(accounts=accounts, settings=settings)
                    if summary.claimed_accounts or summary.stale_pending_marked:
                        logger.info(
                            "Periodic warm-up tick completed checked=%s claimed=%s submitted=%s failed=%s "
                            "skipped=%s stale=%s",
                            summary.checked_accounts,
                            summary.claimed_accounts,
                            summary.submitted_accounts,
                            summary.failed_accounts,
                            summary.skipped_accounts,
                            summary.stale_pending_marked,
                        )
            except Exception:
                logger.exception("Periodic account warm-up loop failed")


@asynccontextmanager
async def _background_accounts_repo() -> AsyncIterator[AccountsRepository]:
    async with get_background_session() as session:
        yield AccountsRepository(session)


def build_periodic_account_warmup_scheduler() -> PeriodicAccountWarmupScheduler:
    return PeriodicAccountWarmupScheduler()
