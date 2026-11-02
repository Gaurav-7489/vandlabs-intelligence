"""Malware-scan status on documents; versioned insight explanations.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ORG = "nullif(current_setting('app.org_id', true), '')"


def upgrade() -> None:
    op.execute("""
    ALTER TABLE documents ADD COLUMN scan_status varchar(20) NOT NULL DEFAULT 'pending', ADD COLUMN scan_detail text;
    CREATE TABLE insight_explanations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      insight_id uuid NOT NULL REFERENCES insights(id) ON DELETE CASCADE, explanation text NOT NULL, source varchar(100) NOT NULL,
      created_by uuid, created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_insight_explanations_org_id ON insight_explanations(org_id);
    CREATE INDEX ix_insight_explanations_insight_id ON insight_explanations(insight_id, created_at DESC);
    ALTER TABLE insight_explanations ENABLE ROW LEVEL SECURITY; ALTER TABLE insight_explanations FORCE ROW LEVEL SECURITY;
    """)
    op.execute(f"CREATE POLICY tenant_isolation ON insight_explanations USING (org_id = ({ORG})::uuid) WITH CHECK (org_id = ({ORG})::uuid);")
    for role in ("vand_app", "vand_worker"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON insight_explanations TO {role}")


def downgrade() -> None:
    op.execute("DROP TABLE insight_explanations; ALTER TABLE documents DROP COLUMN scan_status, DROP COLUMN scan_detail;")
