# ADR-0001: Modular monolith in a monorepo
**Status:** accepted. Single FastAPI codebase + worker entrypoint; React SPA in the same repo. Rationale: one transactional boundary for tenancy,
audit and jobs; lowest operational cost for a first release. Revisit when a module needs independent scaling or stronger isolation (e.g. connector sandboxes).
