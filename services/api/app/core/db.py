"""Async DB access. Every tenant-scoped transaction sets `app.org_id` (transaction-local)
so PostgreSQL Row-Level Security enforces isolation independent of application filters."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings


def make_engine(url: str, settings: Settings | None = None) -> AsyncEngine:
    s = settings or get_settings()
    connect_args = {"statement_cache_size": 0} if s.db_disable_statement_cache else {}
    return create_async_engine(
        url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True,
        pool_recycle=1800, connect_args=connect_args,
    )


class Database:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self._factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def tenant_session(self, org_id: UUID) -> AsyncIterator[AsyncSession]:
        """Transaction scoped to one organization. Commits on success, rolls back on error."""
        async with self._factory() as session, session.begin():
            await session.execute(text("SELECT set_config('app.org_id', :v, true)"), {"v": str(org_id)})
            yield session

    @asynccontextmanager
    async def platform_session(self) -> AsyncIterator[AsyncSession]:
        """Platform scope: may touch organizations/users only. Content tables have no platform policy."""
        async with self._factory() as session, session.begin():
            await session.execute(text("SELECT set_config('app.platform', 'true', true)"))
            yield session

    @asynccontextmanager
    async def user_session(self, user_id: UUID) -> AsyncIterator[AsyncSession]:
        """Reads the user's own memberships / organizations (no tenant content reachable)."""
        async with self._factory() as session, session.begin():
            await session.execute(text("SELECT set_config('app.user_id', :v, true)"), {"v": str(user_id)})
            yield session

    @asynccontextmanager
    async def bare_session(self) -> AsyncIterator[AsyncSession]:
        """No tenant context: only tables without RLS (users) and org-less audit rows are reachable."""
        async with self._factory() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
