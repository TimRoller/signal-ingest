# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html), with phase milestones tagged as `vMAJOR.MINOR.0` and the README phase checklist tracking progress in between.

## [Unreleased]

### In progress
- Phase 3 — LLM plan generation + caching + evals (design pending).

## [0.3.0] — 2026-05-24 — Phase 2: Queue + Worker + Deterministic Cleaning

Upload → enqueue → worker → cleaning plan applied → Parquet in silver. **No LLM yet** (Phase 3); plans are hand-coded.

### Added
- `processing_jobs` table with `job_status` enum, FK to `files`, attempts counter, last_error, lifecycle timestamps. Alembic migration `0002_processing_jobs`.
- `shared/cleaning/` library:
  - `operations.py` — Pydantic discriminated-union ops: rename, coerce_type, parse_date, drop_nulls, fill_null, trim, lowercase
  - `plan.py` — `CleaningPlan` model (version + source + operations list)
  - `apply.py` — pure `apply(plan, df) → df` using polars; raises `PermanentCleaningError` / `TransientCleaningError`
  - `registry.py` — `PLANS` dict with hand-coded `demo` and `vendor_a` plans (Phase 3 will replace with LLM cache)
- `ProcessingJobsRepository` — upsert-queued, mark-running/cleaned/failed, attempt tracking.
- Arq worker (`services/worker/`):
  - `main.py` — `WorkerSettings`, `startup`/`shutdown` hooks, Prometheus HTTP server on port 9100
  - `tasks.py` — `clean_file(file_id)` task: download bronze → polars.read_csv → apply plan → write Parquet to silver → update PG state
  - `metrics.py` — `signal_cleaned_total`, `signal_cleaning_duration_seconds`, `signal_rows_processed`
- `services/ingest_api/queue.py` — `ArqEnqueuer`; `make_pool` lifecycle in app lifespan; upload handler enqueues `clean_file` on successful create.
- `POST /reprocess/{file_id}` — re-enqueues a previously processed file; idempotent.
- `S3Storage` extended with `get_object`, `parse_uri`, `bucket` property for the worker's silver/bronze bucket needs.
- `FilesRepository.set_status` — typed status updates with `error_message` propagation.
- docker-compose: worker env wiring, `arq` as the entrypoint, port 9100 exposed for metrics.
- `docs/phases/phase-2.md` — full design doc covering schema, applier contract, retry policy, idempotency, observability, test plan, scope guardrails.

### Verified
- **31/31 tests green** locally (2 smoke + 11 unit + 18 integration).
- 11 unit tests for the cleaning applier — pure, no containers, cover every op + the demo/vendor_a fixtures.
- 7 worker integration tests via testcontainers (Postgres + Redis + MinIO): upload-to-cleaned end-to-end, DuckDB-readable Parquet, vendor_a plan applies, missing plan → permanent fail, invalid CSV → permanent fail, reprocess idempotency, 404 on unknown file.
- Live `docker compose up`: upload demo CSV → worker cleans in ~77ms → `status="cleaned"` → Parquet at `silver/demo/{yyyy}/{mm}/{dd}/{file_id}.parquet`.
- Worker `/metrics` on port 9100 exposes `signal_cleaned_total{source,result}`, `signal_cleaning_duration_seconds`, `signal_rows_processed` with real per-source labels.

## [0.2.0] — 2026-05-24 — Phase 1: Ingest

`POST /upload` works end-to-end.

### Added
- Postgres `files` table with `(source, sha256)` unique constraint, `file_status` enum (`received` / `processing` / `cleaned` / `failed`), indexes on `created_at DESC` and `status`. Alembic migration `0001_initial_files`.
- SQLAlchemy `FileORM` + Pydantic `FileRecord` / `UploadResponse` / `FileListResponse` in `shared/models/file.py`.
- `FilesRepository` (insert-if-absent via `ON CONFLICT DO NOTHING`, get, list, delete).
- Async SQLAlchemy session factory in `shared/db/session.py`.
- `shared/observability/init.py` — OpenTelemetry tracing (console exporter by default, OTLP-capable), FastAPI auto-instrumentation, Prometheus `/metrics` via `prometheus-fastapi-instrumentator`.
- `services/ingest_api/storage.py` — async S3 client wrapper over `aiobotocore`; ensures bronze bucket on startup; PUT and DELETE operations.
- `services/ingest_api/uploads.py` — multipart upload buffering with sha256 computed mid-stream, source validation against `^[a-z][a-z0-9_]{1,63}$`, content-type validation.
- `services/ingest_api/main.py` — `POST /upload`, `GET /status/{file_id}`, `GET /files?limit&offset&source`, `GET /health`, `GET /metrics`.
- Custom Prometheus metrics: `signal_uploads_total{source, result}`, `signal_upload_bytes{source}` histogram.
- `docker-compose.yml` updates: env wiring for ingest_api, automatic `alembic upgrade head` before uvicorn boots.
- Integration tests using testcontainers (real Postgres + real MinIO, no DB mocks): 13 tests covering happy path, idempotency, bad content-type, malformed source, missing fields, status lookup, list pagination + ordering + filtering, metrics exposure.
- `docs/phases/phase-1.md` — design doc covering schema, contract, idempotency rules, failure modes, observability hooks, and test plan.

### Verified
- `docker compose up -d --build` boots all six services; ingest_api runs Alembic migrations before serving.
- `curl -F file=@sample.csv -F source=demo http://localhost:8000/upload` → 201 with full `FileRecord`.
- Repeated upload of identical bytes from the same source → 201 with `duplicate: true`, same `file_id`, no second MinIO PUT (object key is deterministic).
- Object exists in MinIO at `bronze/{source}/{yyyy}/{mm}/{dd}/{sha256}.csv`.
- `signal_uploads_total{result="created"}` and `signal_uploads_total{result="duplicate"}` both increment on `/metrics`.
- 15/15 tests green (2 smoke + 13 integration).

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
