"""Row-Level Security on `users` (previously readable in full by the app role).

Visible: yourself (app.user_id), members of the current tenant (app.org_id via memberships, itself RLS-scoped),
the explicit identity-resolution step (app.identity_resolution='on': sign-in binding, invitations), platform scope.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ORG = "nullif(current_setting('app.org_id', true), '')"
USER = "nullif(current_setting('app.user_id', true), '')"
IDENT = "current_setting('app.identity_resolution', true) = 'on'"
PLATFORM = "current_setting('app.platform', true) = 'true'"


def upgrade() -> None:
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY; ALTER TABLE users FORCE ROW LEVEL SECURITY;")
    op.execute(f"""CREATE POLICY users_read ON users FOR SELECT USING (
        {IDENT} OR {PLATFORM} OR id = ({USER})::uuid
        OR id IN (SELECT user_id FROM memberships WHERE org_id = ({ORG})::uuid));""")
    # New users are created only while resolving an identity (first sign-in / invitation) or by platform provisioning.
    op.execute(f"CREATE POLICY users_insert ON users FOR INSERT WITH CHECK ({IDENT} OR {PLATFORM});")
    # Only the identity step may bind a subject / update the profile. No DELETE policy: runtime roles cannot delete users.
    op.execute(f"CREATE POLICY users_update ON users FOR UPDATE USING ({IDENT}) WITH CHECK ({IDENT});")


def downgrade() -> None:
    op.execute("DROP POLICY users_read ON users; DROP POLICY users_insert ON users; DROP POLICY users_update ON users;")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY; ALTER TABLE users DISABLE ROW LEVEL SECURITY;")
