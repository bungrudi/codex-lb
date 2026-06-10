from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExternalModelRoute, ExternalProvider


class ExternalModelRoutingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_providers(self) -> Sequence[ExternalProvider]:
        result = await self._session.execute(select(ExternalProvider).order_by(ExternalProvider.id.asc()))
        return result.scalars().all()

    async def get_provider(self, provider_id: str) -> ExternalProvider | None:
        return await self._session.get(ExternalProvider, provider_id)

    async def add_provider(self, provider: ExternalProvider) -> ExternalProvider:
        self._session.add(provider)
        await self._session.commit()
        await self._session.refresh(provider)
        return provider

    async def save_provider(self, provider: ExternalProvider) -> ExternalProvider:
        await self._session.commit()
        await self._session.refresh(provider)
        return provider

    async def delete_provider(self, provider: ExternalProvider) -> None:
        await self._session.delete(provider)
        await self._session.commit()

    async def list_routes(self) -> Sequence[ExternalModelRoute]:
        result = await self._session.execute(
            select(ExternalModelRoute).order_by(ExternalModelRoute.public_model.asc())
        )
        return result.scalars().all()

    async def get_route(self, public_model: str) -> ExternalModelRoute | None:
        return await self._session.get(ExternalModelRoute, public_model)

    async def add_route(self, route: ExternalModelRoute) -> ExternalModelRoute:
        self._session.add(route)
        await self._session.commit()
        await self._session.refresh(route)
        return route

    async def save_route(self, route: ExternalModelRoute) -> ExternalModelRoute:
        await self._session.commit()
        await self._session.refresh(route)
        return route

    async def delete_route(self, route: ExternalModelRoute) -> None:
        await self._session.delete(route)
        await self._session.commit()
