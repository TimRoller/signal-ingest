# Handoff

## State (2026-05-24)
**Phase 1 — shipped.** Repo public, CI green, `POST /upload` end-to-end verified. Ready to start Phase 2.

- Repo: https://github.com/TimRoller/signal-ingest
- Latest release: [v0.2.0](https://github.com/TimRoller/signal-ingest/releases/tag/v0.2.0)

## DoD for Phase 1 — verified
- [x] `POST /upload` accepts CSV, writes to MinIO bronze + row to Postgres, returns 201 with `FileRecord`
- [x] Idempotent on `(source, sha256)` — second call returns 200-equivalent with `duplicate: true` and same `file_id`
- [x] `GET /status/{file_id}` returns row or 404
- [x] `GET /files?limit&offset&source` paginates ordered by `created_at DESC`
- [x] `GET /metrics` exposes Prometheus counters incl. `signal_uploads_total{source,result}`
- [x] Alembic migration applies cleanly to a fresh DB (`0001_initial_files`)
- [x] Integration tests run against real Postgres + real MinIO via testcontainers — 13 tests, all green
- [x] `docker compose up -d --build` boots full stack; ingest_api runs migrations before serving

## Next — Phase 2 (Weeks 3–4)
Goal: deterministic cleaning end-to-end. Upload → Redis enqueue → Arq worker pops job → reads bronze CSV → applies a *hard-coded* per-source cleaning plan (no LLM yet) → writes Parquet to silver → updates `files.status = 'cleaned'`.

Build order to design (in a `docs/phases/phase-2.md` doc, mirroring the Phase 1 doc):

1. **`processing_jobs` table** — references `files.id`; status enum (`queued` / `running` / `cleaned` / `failed`); retry count; `last_error`.
2. **Job enqueue from ingest_api** — on successful upload (or via a separate POST /reprocess), push an Arq job with `file_id` as payload.
3. **Worker bootstrap (Arq)** — connect to Redis, register `clean_file` task; lifespan-style init for shared DB session and S3 client.
4. **Deterministic cleaning plan** — hard-coded `CleaningPlan` Pydantic models per source (e.g., `demo`, `vendor_a`). No LLM. This is the deterministic skeleton; Phase 3 will add LLM plan generation on top.
5. **polars pipeline** — read bronze CSV, apply plan (rename, coerce, drop nulls, etc.), validate against a canonical Pydantic schema, write Parquet to `silver/{source}/{yyyy}/{mm}/{dd}/{file_id}.parquet`.
6. **Status updates** — worker writes `running` on pickup, `cleaned` on success, `failed` + `error_message` on exception.
7. **Observability** — span around clean_file, per-source success/failure counters, rows-processed histogram.
8. **Integration test** — testcontainers spins up PG + Redis + MinIO; upload → wait for worker → assert silver Parquet exists + `files.status='cleaned'`.

Acceptance:
- Upload demo CSV → within ~2s, `GET /status/{file_id}` shows `status: "cleaned"`
- Object exists at `silver/demo/.../{file_id}.parquet`, readable by DuckDB
- `signal_cleaned_total{source="demo"} 1.0` on `/metrics`

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
