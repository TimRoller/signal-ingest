# Handoff

## State (2026-05-24)
**Phase 3 — shipped.** LLM plan generation live with Anthropic tool use. Novel sources call Claude Sonnet, get a validated `CleaningPlan`, cache it in Postgres by `(source, fingerprint, plan_version)`. Identical schemas thereafter cost zero LLM calls. Eval suite gates plan quality at ≥0.90 via on-demand `gh workflow run evals.yml`. Phase 4 is the MCP server.

- Repo: https://github.com/TimRoller/signal-ingest
- Latest release: [v0.4.0](https://github.com/TimRoller/signal-ingest/releases/tag/v0.4.0)

## DoD for Phase 3 — verified
- [x] Novel source upload → LLM generates `CleaningPlan` (Anthropic tool use) → file cleans successfully
- [x] Same schema re-upload → cache hit, no LLM call (asserted via `MockPlanGenerator.calls`)
- [x] Hallucinated column refs → file → `failed`, not cached
- [x] `cleaning_plans` table populated with model + tokens + USD cost per call
- [x] `signal_llm_calls_total`, `signal_llm_cost_usd`, `signal_plan_cache_hits_total`, `signal_plan_cache_misses_total` on worker `/metrics:9100`
- [x] Hard-coded registry sources (`demo`, `vendor_a`) bypass the LLM entirely
- [x] Eval suite: 3 happy + 2 failure-mode datasets; pass threshold 0.90
- [x] `.github/workflows/evals.yml` `workflow_dispatch` job runs against real Anthropic API on demand
- [x] 48/48 tests green in PR CI (mock LLM only)

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

## Next — Phase 4 (Week 6)
Goal: stand up the MCP server so a downstream agent (or Slackbot/UI in Phase 5) can answer natural-language questions over the cleaned data without touching storage directly.

Sketch:

1. **`services/mcp_server/main.py`** — FastMCP server exposing four tools:
   - `search_files(source?, status?, since?, limit, offset)` → list of `FileRecord`
   - `get_file_metadata(file_id)` → full `FileRecord`
   - `query_cleaned_data(sql_template, params)` → DuckDB scan over `silver/...`. Whitelist tables/columns to prevent abuse.
   - `search_by_similarity(query, k)` → pgvector top-k over file-summary embeddings (Phase 4 generates these on clean)
2. **Embedding step** — extend worker's `clean_file` to also embed a short summary (column list + small sample) into pgvector. Adds an `embeddings` table linked to `files`.
3. **Connection from agents** — MCP stdio/HTTP transport. Doc the connection string in README.
4. **Tests** — testcontainers integration: clean a file, ensure all four MCP tools answer correctly.

Acceptance:
- MCP server exposes 4 tools via `fastmcp`.
- `query_cleaned_data` runs DuckDB against MinIO silver Parquet directly.
- `search_by_similarity` returns relevant files for a natural-language query.
- All tools accessible from an MCP client.

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
