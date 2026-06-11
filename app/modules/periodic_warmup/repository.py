from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AccountPeriodicWarmup
from app.db.session import sqlite_writer_section


class PeriodicWarmupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_by_account(self, account_ids: list[str]) -> dict[str, AccountPeriodicWarmup]:
        if not account_ids:
            return {}
        subq = (
            select(
                AccountPeriodicWarmup.id.label("warmup_id"),
                func.row_number()
                .over(
                    partition_by=AccountPeriodicWarmup.account_id,
                    order_by=(AccountPeriodicWarmup.attempted_at.desc(), AccountPeriodicWarmup.id.desc()),
                )
                .label("row_number"),
            )
            .where(AccountPeriodicWarmup.account_id.in_(account_ids))
            .subquery()
        )
        stmt = (
            select(AccountPeriodicWarmup)
            .join(subq, AccountPeriodicWarmup.id == subq.c.warmup_id)
            .where(subq.c.row_number == 1)
        )
        result = await self._session.execute(stmt)
        return {entry.account_id: entry for entry in result.scalars().all()}

    async def try_create_claim(
        self,
        *,
        account_id: str,
        claim_key: str,
        model: str,
        attempted_at: datetime,
    ) -> AccountPeriodicWarmup | None:
        row = AccountPeriodicWarmup(
            account_id=account_id,
            claim_key=claim_key,
            status="pending",
            model=model,
            attempted_at=attempted_at,
        )
        self._session.add(row)
        try:
            async with sqlite_writer_section():
                await self._session.commit()
                await self._session.refresh(row)
        except IntegrityError:
            await self._session.rollback()
            return None
        return row

    async def complete_attempt(
        self,
        attempt_id: int,
        *,
        status: str,
        completed_at: datetime,
        request_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AccountPeriodicWarmup | None:
        stmt = (
            update(AccountPeriodicWarmup)
            .where(AccountPeriodicWarmup.id == attempt_id)
            .values(
                status=status,
                completed_at=completed_at,
                request_id=request_id,
                error_code=error_code,
                error_message=error_message,
                updated_at=completed_at,
            )
            .returning(AccountPeriodicWarmup.id)
        )
        async with sqlite_writer_section():
            result = await self._session.execute(stmt)
            await self._session.commit()
        if result.scalar_one_or_none() is None:
            return None
        row = await self._session.get(AccountPeriodicWarmup, attempt_id)
        if row is not None:
            await self._session.refresh(row)
        return row

    async def mark_stale_pending(self, *, cutoff: datetime, completed_at: datetime) -> int:
        stmt = (
            update(AccountPeriodicWarmup)
            .where(
                AccountPeriodicWarmup.status == "pending",
                AccountPeriodicWarmup.attempted_at < cutoff,
            )
            .values(
                status="failed",
                completed_at=completed_at,
                error_code="stale_pending",
                error_message="Periodic warm-up attempt was abandoned before completion",
                updated_at=completed_at,
            )
            .returning(AccountPeriodicWarmup.id)
        )
        async with sqlite_writer_section():
            result = await self._session.execute(stmt)
            rows = result.scalars().all()
            await self._session.commit()
        return len(rows)
