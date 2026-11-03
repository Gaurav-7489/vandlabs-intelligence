from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    import os
    # OWNER_DATABASE_URL is deliberately NOT a VAND_* setting: it exists only in the migration job, never in API/worker runtime.
    return config.get_main_option("sqlalchemy.url") or os.environ.get("OWNER_DATABASE_URL") or get_settings().migration_database_url


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
