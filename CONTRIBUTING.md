# Contributing
Feature branches + pull requests into `main`; no direct pushes. Before opening a PR run: `ruff check . && mypy app && pytest -q` (services/api) and
`npm run typecheck && npm run lint && npm test && npm run build` (apps/web). Schema changes need an Alembic migration and must keep `test_models_match_migrations` green.
Any new tenant table needs `org_id`, RLS policy, grants, and a cross-tenant test. Never log document contents or secrets.
