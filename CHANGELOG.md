# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html), with phase milestones tagged as `vMAJOR.MINOR.0` and the README phase checklist tracking progress in between.

## [Unreleased]

### In progress
- Phase 1 — `POST /upload` endpoint, MinIO bronze write, Postgres `files` row, Alembic migration, integration test via testcontainers.

## [0.1.0] — 2026-05-24 — Phase 0: Scaffold

First release. **Empty but well-scaffolded.** The repo boots end-to-end on a fresh machine.

### Added
- Project skeleton: `services/{ingest_api,worker,mcp_server,slackbot}`, `shared/{models,db,observability}`, `evals/`, `infra/{grafana,prometheus}`, `tests/{integration,e2e}`.
- FastAPI stubs for `ingest_api` and `mcp_server`, each exposing `/health` returning `{"ok": true}`.
- Python stubs for `worker` and `slackbot`.
- `docker-compose.yml` orchestrating six services: `postgres` (with pgvector), `redis`, `minio`, `ingest_api`, `mcp_server`, `worker`. Healthchecks on the three infra services. Volumes for PG and MinIO data persistence.
- Multi-service `Dockerfile` built on `python:3.12-slim` with `uv sync --frozen --no-dev`, venv on `PATH`.
- GitHub Actions CI workflow: `uv sync` → `ruff check` → `ruff format --check` → `mypy` → `pytest`.
- Tool configuration in `pyproject.toml` for ruff (line-length 100, target py312, select E/F/I/B/UP/SIM/ASYNC), mypy (`strict = true`), and pytest (asyncio auto mode).
- Two smoke tests verifying both FastAPI `/health` endpoints return 200.
- `README.md` with Mermaid architecture diagram, four-store table, run-locally instructions, phase checklist.
- `PLAN.md` — standalone build plan (sanitized of any PII before publishing).
- `HANDOFF.md` — cold-start brief for next session, covering Phase 0 DoD verification and Phase 1 build order.
- Five Architecture Decision Records in `docs/adr/`:
  - 0001 — Four-store data architecture
  - 0002 — Real Postgres in tests via testcontainers, not mocks
  - 0003 — LLM as labeler, code as worker — plan-once-per-fingerprint
  - 0004 — Observability from day one, not "later"
  - 0005 — pgvector on the same Postgres, not a separate vector DB
- `LICENSE` (MIT).

### Verified
- `docker compose up -d --build` brings up all six services on a clean machine.
- `postgres`, `redis`, `minio` report `(healthy)` from their docker-compose healthchecks.
- `curl http://localhost:8000/health` → `200 {"ok": true}`.
- `curl http://localhost:8001/health` → `200 {"ok": true}`.
- CI green on `main`.

### Notes
- CI annotations to address in a future cleanup (non-blocking): `actions/checkout@v4` and `astral-sh/setup-uv@v3` will need to migrate from Node 20 to Node 24 by mid-2026.
