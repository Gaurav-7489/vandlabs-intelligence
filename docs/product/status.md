# Product status (Phase 0 + first Phase 1 slice)

Categories: **IT** implemented and tested · **I** implemented, not fully verified · **P** partial · **N** not implemented · **B** blocked by external configuration.

| Area | Status | Notes |
|---|---|---|
| Multi-tenant schema, RLS, RBAC, MFA gate, platform provisioning | IT | 41 backend tests |
| Audit trail (append-only) + auditor view | IT | |
| Rate limiting (Redis token bucket, fail-closed policy) | IT | thresholds untuned, no load test |
| Secure upload + background ingestion | IT for CSV/TXT end to end; **I** for XLSX/DOCX/PDF parsers | Real XLSX/DOCX/PDF content has only signature/corrupt-file tests; add fixture files |
| Commitment extraction + deterministic risk rules + insights | IT | 3 rules: overdue, blocked-by-dependency, unowned |
| Keyword search (tenant-scoped) | IT | |
| Grounded explain / ask | IT with a fake provider; **I** with real models | Anthropic/OpenAI HTTP adapters written, never called against live APIs; price table empty so USD cost is not computed (tokens are) |
| Decisions, approvals, verified idempotent execution, outcomes | IT | One action type: `create_task` |
| Web app: shell, design system, light/dark, 8 areas | IT (browser E2E, typecheck, lint, 32 contrast checks) | No screen-reader/manual a11y audit; no Lighthouse/Core Web Vitals measurement |
| Authentication with a real IdP | B | Provider not chosen (ADR-0004) |
| Cloudflare WAF/Turnstile, Neon, R2, secrets, backups, staging | B | Needs accounts/credentials; S3/R2 adapter unverified |
| Connectors (Drive, GitHub) | N | UI shows true "Not connected" |
| Knowledge graph, entity resolution, embeddings/hybrid search | N | Phase 2 (ADR-0005) |
| Streaming AI answers (SSE) | N | Ask returns a single response |
| Cost dashboard, observability stack, load tests | N | Usage accounting + `/usage/ai` exist |
| OCR | N | Scanned PDFs flagged `requires_review` |
| Agent classes | N | Only the narrow deterministic `create_task` execution path exists |
| Typed API client generation | N | TS types hand-maintained; OpenAPI exported to `docs/api` |

## Known limitations
- Insight rules rely on a `depends on` column; undeclared dependencies are not inferred. Dates must be ISO (`YYYY-MM-DD`) or real spreadsheet dates; ambiguous formats are rejected and flagged, never guessed.
- A decision's requester cannot approve it (even owners) by design; single-person organizations need a second approver.
- The stored explanation on an insight is overwritten by the latest "Explain" call.
- The SPA token is memory-only (reload = sign in again) until a production auth flow exists.
- Parsing runs in the worker process with row/char caps but no OS-level sandbox or timeout.
- CI workflow is written but has not yet run on GitHub.
