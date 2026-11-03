# ADR-0003: Durable job queue in PostgreSQL (SKIP LOCKED)
**Status:** accepted for release 1. Jobs are written in the same transaction as the business change (no dual-write loss), with retries + exponential backoff,
dead-letter status, idempotency keys, and stale-lock recovery (a crashed worker's job is re-run, never marked successful). Handlers are idempotent.
**Trade-off:** polling (1s) and Postgres load; no scheduled/cron or priority queues yet. Revisit (e.g. Redis/Streams, SQS) when throughput or scheduling needs it.
