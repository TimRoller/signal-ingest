# Handoff

## State (2026-05-24)
**Phase 0 — shipped.** Repo public, CI green, docker-compose verified. Ready to start Phase 1.

- Repo: https://github.com/TimRoller/signal-ingest
- `main` is two commits ahead of empty:
  - `b717191` feat: scaffold signal-ingest (Phase 0)
  - `863098b` fix(docker): put uv venv on PATH so service entrypoints find uvicorn

## Definition of Done for Phase 0 — verified
- [x] Six containers boot: postgres+pgvector, redis, minio, ingest_api, mcp_server, worker
- [x] postgres/redis/minio report `(healthy)` via docker-defined healthchecks
- [x] `curl http://localhost:8000/health` → `{"ok": true}`
- [x] `curl http://localhost:8001/health` → `{"ok": true}`
- [x] CI on `main` is green (ruff + ruff format + mypy + pytest)
- [x] README has architecture diagram + four-store table + phase checklist
- [x] PLAN.md copied in (sanitized — no PII in public repo)

## Next — Phase 1 (Weeks 1–2)
Goal: `POST /upload` accepts a CSV, streams to MinIO bronze, writes a row to Postgres `files`, returns `{file_id, status: "received"}`.

Build order:
1. **Postgres schema + Alembic.** `files` table: id, source, original_name, sha256, byte_size, s3_uri, status (enum), created_at, updated_at. Alembic migration scripted from day one — no DB-side schema drift allowed.
2. **MinIO client.** aiobotocore (async S3). Stream upload from FastAPI `UploadFile` to `bronze/{source}/{yyyy}/{mm}/{dd}/{sha256}.csv`.
3. **`POST /upload` endpoint.** Multipart form. Compute sha256 mid-stream. On success write PG row and return 201 + `file_id`. Idempotent on `(source, sha256)`.
4. **`GET /status/{file_id}` + `GET /files`.** Repository pattern in `shared/db/repositories/`.
5. **Observability from start.** OTel SDK init in app startup; instrument FastAPI, asyncpg, aiobotocore. Prometheus `/metrics` endpoint on ingest_api. Pinned decision per PLAN.md §4.
6. **Tests via testcontainers.** No DB mocks. Real Postgres + MinIO containers spun up per test session. Cover happy path + 2 failure modes (duplicate sha256, upload mid-stream disconnect).

Acceptance:
- `curl -F 'file=@sample.csv' http://localhost:8000/upload` → 201 with `{file_id, status}`
- `GET /status/{file_id}` → JSON row
- `GET /files` → paginated list
- Integration test green locally and in CI
- Prometheus metrics scrape-able from ingest_api `:8000/metrics`

## Operational Notes
- **Docker runtime is OrbStack** (`brew install --cask orbstack`). docker CLI at `~/.orbstack/bin/docker` — interactive shell finds it via OrbStack's shell init, but the Claude Bash tool may not; prepend `export PATH="$HOME/.orbstack/bin:$PATH"` in commands if `docker` is "not found".
- **Run locally:**
  ```
  docker compose up -d --build
  curl http://localhost:8000/health
  curl http://localhost:8001/health
  docker compose down
  ```
- **Git author identity** for commits in this repo: `TimRoller <23110001+TimRoller@users.noreply.github.com>` (GitHub privacy-safe noreply). Use `git -c user.email=... -c user.name=...` overrides on commits, since no `git config` was set repo-locally.
- **CI annotations** to clean up later (non-blocking): `actions/checkout@v4` and `astral-sh/setup-uv@v3` are on Node 20, deprecated June 2026.

## Pinned Decisions (from PLAN.md — do not relitigate)
- Real Postgres in tests via testcontainers. Never mock the DB.
- LLM is labeler, code is worker. Plan caching is non-negotiable cost discipline.
- Observability bakes in from Phase 1, not "later".
- pgvector on same Postgres, not Pinecone — graduate only past ~5M vectors.

## When Stuck — read in this repo
- `PLAN.md` — full plan, sections 3 (four-store), 4 (stack), 6 (architecture), 7 (phases), 10 (anti-patterns)
- `README.md` — architecture diagram + four-store table

## Cross-repo Pointer
The "WHY" docs (storage deep-dive, evals guide, distributed-systems primer) live in `~/projects/learning/data/`. Reference but don't link to them from this repo — `learning` is private.
