"""Read-only grants for the logical-backup role (if it exists).

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Conditional: environments without a backup role (e.g. throwaway test DBs) still migrate cleanly.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vand_backup') THEN
        GRANT USAGE ON SCHEMA public TO vand_backup;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO vand_backup;
        GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO vand_backup;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO vand_backup;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO vand_backup;
      END IF;
    END $$;""")


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vand_backup') THEN
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM vand_backup;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM vand_backup;
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM vand_backup;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM vand_backup;
        REVOKE USAGE ON SCHEMA public FROM vand_backup;
      END IF;
    END $$;""")
