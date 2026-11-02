"""Initial schema: tenancy, documents, commitment intelligence, decisions, jobs, audit, RLS.

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "memberships", "documents", "document_chunks", "commitments", "tasks", "insights", "decisions",
    "approvals", "executions", "outcomes", "ai_usage",
]
# nullif: after a transaction-local SET the GUC reads back as '' (not NULL) on a reused pooled connection.
ORG = "nullif(current_setting('app.org_id', true), '')"
USER = "nullif(current_setting('app.user_id', true), '')"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("""
    CREATE TABLE organizations (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name varchar(200) NOT NULL, slug varchar(80) NOT NULL UNIQUE,
      status varchar(20) NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), subject varchar(255) UNIQUE, email varchar(320) NOT NULL UNIQUE,
      display_name varchar(200), is_platform_admin boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now());
    CREATE TABLE memberships (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      user_id uuid NOT NULL REFERENCES users(id), role varchar(20) NOT NULL, department varchar(100),
      status varchar(20) NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, user_id), CHECK (role IN ('owner','admin','manager','staff','viewer','auditor')));
    CREATE INDEX ix_memberships_org_id ON memberships(org_id); CREATE INDEX ix_memberships_user_id ON memberships(user_id);

    CREATE TABLE audit_events (
      id bigserial PRIMARY KEY, org_id uuid, actor_user_id uuid, action varchar(80) NOT NULL, resource_type varchar(60),
      resource_id varchar(80), outcome varchar(20) NOT NULL DEFAULT 'success', ip varchar(64), request_id varchar(64),
      metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_audit_events_org_id ON audit_events(org_id, id DESC); CREATE INDEX ix_audit_events_action ON audit_events(action);

    CREATE TABLE documents (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      filename varchar(255) NOT NULL, detected_type varchar(20) NOT NULL, size_bytes bigint NOT NULL, sha256 varchar(64) NOT NULL,
      storage_key varchar(300) NOT NULL, status varchar(20) NOT NULL DEFAULT 'queued', error text,
      stats jsonb NOT NULL DEFAULT '{}', version integer NOT NULL DEFAULT 1, uploaded_by uuid NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz);
    CREATE INDEX ix_documents_org_id ON documents(org_id); CREATE INDEX ix_documents_org_created ON documents(org_id, created_at, id);
    CREATE TABLE document_chunks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE, ordinal integer NOT NULL, text text NOT NULL,
      locator varchar(120) NOT NULL, tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
      created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_document_chunks_org_id ON document_chunks(org_id); CREATE INDEX ix_document_chunks_document_id ON document_chunks(document_id);
    CREATE INDEX ix_chunks_tsv ON document_chunks USING gin(tsv);

    CREATE TABLE commitments (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      external_key varchar(200) NOT NULL, title varchar(500) NOT NULL, customer varchar(200), owner_name varchar(200),
      owner_email varchar(320), due_date date, status varchar(20) NOT NULL DEFAULT 'open', depends_on varchar[] NOT NULL DEFAULT '{}',
      source_document_id uuid REFERENCES documents(id) ON DELETE SET NULL, source_locator varchar(120),
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE (org_id, external_key));
    CREATE INDEX ix_commitments_org_id ON commitments(org_id); CREATE INDEX ix_commitments_due ON commitments(org_id, due_date);
    CREATE TABLE tasks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      external_key varchar(200), title varchar(500) NOT NULL, owner_name varchar(200), owner_email varchar(320), due_date date,
      status varchar(20) NOT NULL DEFAULT 'todo', origin varchar(20) NOT NULL DEFAULT 'imported', decision_id uuid,
      source_document_id uuid REFERENCES documents(id) ON DELETE SET NULL, source_locator varchar(120), created_by uuid,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_tasks_org_id ON tasks(org_id); CREATE INDEX ix_tasks_org_created ON tasks(org_id, created_at, id);
    CREATE UNIQUE INDEX ux_tasks_org_key ON tasks(org_id, external_key) WHERE external_key IS NOT NULL;

    CREATE TABLE insights (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      fingerprint varchar(64) NOT NULL, rule varchar(60) NOT NULL, severity varchar(10) NOT NULL, status varchar(20) NOT NULL DEFAULT 'open',
      title varchar(500) NOT NULL, summary text NOT NULL, commitment_id uuid REFERENCES commitments(id) ON DELETE SET NULL,
      evidence jsonb NOT NULL DEFAULT '[]', uncertainty text NOT NULL DEFAULT '', recommended_step text NOT NULL DEFAULT '',
      explanation text, explanation_source varchar(100),
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE (org_id, fingerprint));
    CREATE INDEX ix_insights_org_id ON insights(org_id); CREATE INDEX ix_insights_org_created ON insights(org_id, created_at, id);
    CREATE TABLE decisions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      insight_id uuid REFERENCES insights(id) ON DELETE SET NULL, title varchar(500) NOT NULL, business_question text NOT NULL,
      observation text NOT NULL, evidence jsonb NOT NULL DEFAULT '[]', alternatives jsonb NOT NULL DEFAULT '[]',
      recommended_action jsonb NOT NULL, risks text NOT NULL DEFAULT '', success_criteria text NOT NULL DEFAULT '',
      state varchar(30) NOT NULL DEFAULT 'recommendation_ready', requested_by uuid NOT NULL, approver_user_id uuid,
      version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_decisions_org_id ON decisions(org_id); CREATE INDEX ix_decisions_org_created ON decisions(org_id, created_at, id);
    CREATE TABLE approvals (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      decision_id uuid NOT NULL REFERENCES decisions(id) ON DELETE CASCADE, actor_user_id uuid NOT NULL, action varchar(20) NOT NULL,
      comment text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_approvals_org_id ON approvals(org_id); CREATE INDEX ix_approvals_decision_id ON approvals(decision_id);
    CREATE TABLE executions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      decision_id uuid NOT NULL REFERENCES decisions(id) ON DELETE CASCADE, action_type varchar(40) NOT NULL,
      idempotency_key varchar(120) NOT NULL, status varchar(20) NOT NULL DEFAULT 'pending', verified boolean NOT NULL DEFAULT false,
      result jsonb NOT NULL DEFAULT '{}', error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (org_id, idempotency_key));
    CREATE INDEX ix_executions_org_id ON executions(org_id); CREATE INDEX ix_executions_decision_id ON executions(decision_id);
    CREATE TABLE outcomes (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id),
      decision_id uuid NOT NULL REFERENCES decisions(id) ON DELETE CASCADE, recorded_by uuid NOT NULL, result varchar(20) NOT NULL,
      notes text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_outcomes_org_id ON outcomes(org_id); CREATE INDEX ix_outcomes_decision_id ON outcomes(decision_id);

    CREATE TABLE jobs (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id), kind varchar(60) NOT NULL,
      payload jsonb NOT NULL DEFAULT '{}', status varchar(20) NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
      max_attempts integer NOT NULL DEFAULT 4, run_at timestamptz NOT NULL DEFAULT now(), locked_at timestamptz, locked_by varchar(80),
      idempotency_key varchar(120), last_error text, result jsonb NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_jobs_org_id ON jobs(org_id); CREATE INDEX ix_jobs_claim ON jobs(status, run_at);
    CREATE UNIQUE INDEX ux_jobs_idem ON jobs(org_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
    CREATE TABLE ai_usage (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES organizations(id), user_id uuid,
      task varchar(40) NOT NULL, provider varchar(30) NOT NULL, model varchar(80) NOT NULL, prompt_version varchar(20) NOT NULL,
      input_tokens integer NOT NULL DEFAULT 0, output_tokens integer NOT NULL DEFAULT 0, cost_usd numeric(12,6) NOT NULL DEFAULT 0,
      status varchar(20) NOT NULL, latency_ms integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now());
    CREATE INDEX ix_ai_usage_org_id ON ai_usage(org_id, created_at);
    """)

    # ---- Row-Level Security: tenant tables. FORCE so even the table owner is subject to policy.
    for t in TENANT_TABLES + ["jobs"]:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING (org_id = ({ORG})::uuid) WITH CHECK (org_id = ({ORG})::uuid);")
    # Worker may claim jobs across tenants (jobs table only). Every other table stays tenant-scoped for the worker.
    op.execute("CREATE POLICY worker_claim ON jobs TO vand_worker USING (true) WITH CHECK (true);")

    # A user may read their OWN membership rows without a tenant context (to list "my organizations").
    op.execute(f"CREATE POLICY self_read ON memberships FOR SELECT USING (user_id = ({USER})::uuid);")

    # organizations: its own tenant context, orgs the current user belongs to, or platform scope (provisioning/listing).
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY; ALTER TABLE organizations FORCE ROW LEVEL SECURITY;")
    op.execute(f"""CREATE POLICY org_scope ON organizations FOR SELECT
        USING (id = ({ORG})::uuid OR current_setting('app.platform', true) = 'true'
               OR id IN (SELECT org_id FROM memberships WHERE user_id = ({USER})::uuid));
        CREATE POLICY org_write ON organizations FOR INSERT WITH CHECK (current_setting('app.platform', true) = 'true');
        CREATE POLICY org_update ON organizations FOR UPDATE USING (current_setting('app.platform', true) = 'true');""")

    # audit: own-tenant rows readable; inserts allowed for own tenant or org-less security events. Append-only.
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY; ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;")
    op.execute(f"CREATE POLICY audit_read ON audit_events FOR SELECT USING (org_id = ({ORG})::uuid);")
    op.execute(f"CREATE POLICY audit_insert ON audit_events FOR INSERT WITH CHECK (org_id IS NULL OR org_id = ({ORG})::uuid);")
    op.execute("""
    CREATE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$;
    CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION audit_immutable();
    CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();
    """)

    # ---- Grants: least privilege for runtime roles.
    for role in ("vand_app", "vand_worker"):
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {role}")
        op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
        op.execute(f"REVOKE DELETE ON organizations FROM {role}")


def downgrade() -> None:
    # Destructive: drops ALL data. Refuse unless explicitly acknowledged (never in production).
    import os
    if os.environ.get("VAND_ALLOW_DESTRUCTIVE_DOWNGRADE") != "yes-i-understand":
        raise RuntimeError("Downgrading 0001 drops the entire schema. Set VAND_ALLOW_DESTRUCTIVE_DOWNGRADE=yes-i-understand (non-production only).")
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
