"""Async DB access. Every tenant-scoped transaction sets `app.org_id` (transaction-local)
so PostgreSQL Row-Level Security enforces isolation independent of application filters."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings

_LIBPQ_ONLY = {"sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey", "target_session_attrs"}


def with_driver(url: str, driver: str) -> str:
    """Providers (Neon, Render) hand out `postgres://` / `postgresql://` URLs; SQLAlchemy would pick psycopg2 (not installed)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return f"postgresql+{driver}://" + url[len(prefix):]
    return url


def normalize_asyncpg_url(url: str) -> tuple[str, dict[str, Any]]:
    """Hosted Postgres URLs (Neon, etc.) carry libpq params such as `sslmode=require&channel_binding=require`.
    SQLAlchemy forwards query params to asyncpg.connect(), which rejects them. Translate TLS intent to asyncpg's `ssl`
    and drop libpq-only params. TLS is never silently downgraded: any sslmode other than disable/allow/prefer => required."""
    u = make_url(with_driver(url, "asyncpg"))
    q = dict(u.query)
    args: dict[str, Any] = {}
    mode = q.get("sslmode")
    if isinstance(mode, str) and mode not in ("disable", "allow", "prefer"):
        args["ssl"] = "verify-full" if mode == "verify-full" else "require"
    for k in _LIBPQ_ONLY:
        q.pop(k, None)
    return u.set(query=q).render_as_string(hide_password=False), args


def make_engine(url: str, settings: Settings | None = None) -> AsyncEngine:
    s = settings or get_settings()
    url, connect_args = normalize_asyncpg_url(url)
    if s.db_disable_statement_cache:
        # Transaction-mode poolers (Neon pooled endpoint / PgBouncer): no cached or reused prepared statement names.
        connect_args |= {"statement_cache_size": 0, "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4().hex}__"}
        url = make_url(url).update_query_dict({"prepared_statement_cache_size": "0"}).render_as_string(hide_password=False)
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
    async def identity_session(self) -> AsyncIterator[AsyncSession]:
        """The sign-in identity-resolution step only: may look up/create/bind `users` rows (no tenant content)."""
        async with self._factory() as session, session.begin():
            await session.execute(text("SELECT set_config('app.identity_resolution', 'on', true)"))
            yield session

    @asynccontextmanager
    async def bare_session(self) -> AsyncIterator[AsyncSession]:
        """No tenant context: only tables without RLS (users) and org-less audit rows are reachable."""
        async with self._factory() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
