-- Synthetic org + users for the OIDC browser E2E (run as vand_owner against the dev DB).
BEGIN;
SELECT set_config('app.platform','true',true);
INSERT INTO organizations (id,name,slug) VALUES ('11111111-1111-1111-1111-111111111111','E2E Org (synthetic)','e2e-oidc') ON CONFLICT DO NOTHING;
SELECT set_config('app.org_id','11111111-1111-1111-1111-111111111111',true);
INSERT INTO users (email) VALUES ('owner@e2e.example.com'),('staff@e2e.example.com') ON CONFLICT DO NOTHING;
INSERT INTO memberships (org_id,user_id,role) SELECT '11111111-1111-1111-1111-111111111111',id,'owner' FROM users WHERE email='owner@e2e.example.com' ON CONFLICT DO NOTHING;
INSERT INTO memberships (org_id,user_id,role) SELECT '11111111-1111-1111-1111-111111111111',id,'staff' FROM users WHERE email='staff@e2e.example.com' ON CONFLICT DO NOTHING;
COMMIT;
