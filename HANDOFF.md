# Handoff

## State (2026-05-24)
**Phase 2 — shipped.** Worker pipeline live: upload → enqueue → polars cleaning → Parquet in silver → status flips to `cleaned`. Hand-coded plans for `demo` and `vendor_a`. Phase 3 swaps in LLM plan generation on the same boundary.

- Repo: https://github.com/TimRoller/signal-ingest
- Latest release: [v0.3.0](https://github.com/TimRoller/signal-ingest/releases/tag/v0.3.0)

## DoD for Phase 2 — verified
- [x] Upload demo CSV → within ~1s, status flips to `cleaned`
- [x] Parquet at `silver/{source}/{yyyy}/{mm}/{dd}/{file_id}.parquet`, readable by DuckDB
- [x] `processing_jobs` row tracks the run (queued → running → cleaned/failed) with attempts + timing
- [x] Re-running is idempotent (silver overwritten, no orphan rows)
- [x] Invalid CSV → status `failed` with `error_message`
- [x] `POST /reprocess/{file_id}` re-enqueues a previously processed file
- [x] `signal_cleaned_total{source,result}`, `signal_cleaning_duration_seconds{source}`, `signal_rows_processed{source}` on worker `/metrics` port 9100
- [x] All 31 tests green (2 smoke + 11 unit + 18 integration); testcontainers spin up PG + Redis + MinIO

## DoD for Phase 1 — verified
- [x] `POST /upload` accepts CSV, writes to MinIO bronze + row to Postgres, returns 201 with `FileRecord`
- [x] Idempotent on `(source, sha256)` — second call returns 200-equivalent with `duplicate: true` and same `file_id`
- [x] `GET /status/{file_id}` returns row or 404
- [x] `GET /files?limit&offset&source` paginates ordered by `created_at DESC`
- [x] `GET /metrics` exposes Prometheus counters incl. `signal_uploads_total{source,result}`
- [x] Alembic migration applies cleanly to a fresh DB (`0001_initial_files`)
- [x] Integration tests run against real Postgres + real MinIO via testcontainers — 13 tests, all green
- [x] `docker compose up -d --build` boots full stack; ingest_api runs migrations before serving

## Next — Phase 3 (Week 5)
Goal: replace hand-coded cleaning plans with **LLM-generated** plans, keyed and cached by schema fingerprint. The `CleaningPlan` Pydantic model from Phase 2 is the LLM's exact output contract — already validated, already applied by deterministic code (ADR 0003).

Sketch of what Phase 3 introduces:

1. **`cleaning_plans` table** — stores plans keyed by `(source, fingerprint)`. Fingerprint = `hash(source, sorted column names, sample column types)`.
2. **Plan generator** — Anthropic SDK client; prompts the LLM to emit a `CleaningPlan` JSON object given (file head, column names). Output validated against the Pydantic discriminated union.
3. **Registry rewires to cache** — `get_plan(source, fingerprint)` now hits the PG cache first; on miss, calls the LLM, validates, persists, returns. The applier doesn't change.
4. **Eval suite** — golden CSVs + expected canonical outputs in `evals/datasets/`; a CI-gated suite that grades LLM-generated plans against expected behavior. Use the `evals-guide.html` patterns.
5. **Model routing** — Sonnet for novel/complex schemas, Haiku for retries on simpler shapes.
6. **Cost discipline** — `signal_llm_cost_usd{model, source}` counter; plan reuse metrics.

Acceptance:
- Upload a CSV from a *new* source (no hand-coded plan) → LLM generates plan → file cleans successfully.
- Re-upload the same shape → cache hit, no LLM call (verified via metric).
- Eval suite has ≥10 golden datasets + ≥3 failure-mode datasets, CI-gated.
- LLM cost per file is bounded and visible in `/metrics`.

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
