# ADR 0002: Real Postgres in tests via testcontainers, not mocks

## Status
Accepted — 2026-05-24

## Context
Database tests can be written against either:

1. **A mock or in-memory substitute** (e.g., SQLite, an in-memory dict, a hand-written fake) — fast, hermetic, but a different engine.
2. **A real Postgres instance** spun up per test session — slower start, but the same engine as production.

The historical failure mode of option 1: a mocked or substituted DB passes every test, then the production migration fails because:
- The fake doesn't enforce real constraints (FKs, NOT NULL, CHECK, unique partial indexes)
- The fake doesn't reproduce Postgres-specific behavior (transaction isolation levels, `ON CONFLICT`, `RETURNING`, partial indexes, `tsvector`, `pgvector`)
- The fake silently accepts queries that real Postgres rejects (or vice versa)

This project uses `pgvector` — a Postgres-only extension — and depends on Postgres-specific features (`ON CONFLICT`, JSONB, partial indexes). A mock would diverge from production behavior on day one.

## Decision
All database tests use a real Postgres 16 instance via [testcontainers-python](https://testcontainers.com/), with the `pgvector/pgvector:pg16` image (same image as production). The container is spun up once per test session and shared across tests.

Repository methods are tested against this real DB. No SQLAlchemy mocking. No SQLite substitute. No hand-written fake.

## Consequences

**Positive:**
- Test failures reflect real Postgres behavior. Migrations that work in tests will work in production.
- `pgvector` queries, `ON CONFLICT`, JSONB operators, and transaction semantics are exercised by every test run.
- Same image in CI, local dev, and prod — one less environment drift surface.

**Negative:**
- Test session startup is ~3–5 seconds slower (container boot + migration).
- CI runners need Docker available. (GitHub Actions runners do by default.)
- Tests are not parallelizable across the same DB without per-test schemas or transactions-with-rollback.

## Mitigation for slowness
- Use `pytest-asyncio` session-scoped fixtures so the container starts once.
- Wrap each test in a transaction that rolls back at teardown for isolation without re-creating schema.

## Alternatives considered
- **SQLite for tests.** Rejected: no pgvector, no JSONB, different transaction semantics, no `ON CONFLICT (...) DO UPDATE`.
- **Mocked repository layer.** Rejected: tests pass, integration breaks — common, costly, hard to debug.
- **Shared dev Postgres for tests.** Rejected: tests pollute each other; CI cannot reproduce.
