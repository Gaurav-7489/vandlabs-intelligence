-- Synthetic orgs/users for a LOCAL rehearsal of acceptance.mjs (test issuer). Run as vand_owner against the dev DB.
BEGIN;
SELECT set_config('app.platform','true',true);
INSERT INTO organizations (id,name,slug) VALUES ('22222222-2222-2222-2222-222222222222','Rehearsal Org A (synthetic)','rehearsal-a'),
                                                ('33333333-3333-3333-3333-333333333333','Rehearsal Org B (synthetic)','rehearsal-b') ON CONFLICT DO NOTHING;
INSERT INTO users (email) VALUES ('req@rehearsal.example.com'),('appr@rehearsal.example.com'),('aud@rehearsal.example.com'),('out@rehearsal.example.com') ON CONFLICT DO NOTHING;
SELECT set_config('app.org_id','22222222-2222-2222-2222-222222222222',true);
INSERT INTO memberships (org_id,user_id,role) SELECT '22222222-2222-2222-2222-222222222222',id,r FROM (VALUES ('req@rehearsal.example.com','manager'),('appr@rehearsal.example.com','manager'),('aud@rehearsal.example.com','auditor')) v(e,r) JOIN users u ON u.email=v.e ON CONFLICT DO NOTHING;
SELECT set_config('app.org_id','33333333-3333-3333-3333-333333333333',true);
INSERT INTO memberships (org_id,user_id,role) SELECT '33333333-3333-3333-3333-333333333333',id,'manager' FROM users WHERE email='out@rehearsal.example.com' ON CONFLICT DO NOTHING;
COMMIT;
