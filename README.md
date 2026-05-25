# signal-ingest

> A production-shaped data ingestion + serving platform: messy CSVs in, deterministic LLM-driven cleaning, exposed via an MCP server, queryable from a Slackbot or web UI. The repo is the artifact — the answer to *"have you ever built a system?"*

**Status:** 🚧 Phase 0 — scaffold complete

---

## Architecture

```
                        ┌─────────────────────────┐
                        │  Slackbot / Web UI      │
                        │  (consumer surface)     │
                        └───────────┬─────────────┘
                                    │  natural-language query
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR AGENT  (LangGraph + Claude Sonnet)                │
│  · plans sections, calls MCP tools, assembles answer            │
└────────────────────────────┬────────────────────────────────────┘
                             │  MCP stdio / HTTP
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MCP SERVER  (FastMCP)                                          │
│  Tools:                                                         │
│  · search_files(filters)                                        │
│  · get_file_metadata(file_id)                                   │
│  · query_cleaned_data(sql_template, params)                     │
│  · search_by_similarity(query, k)                               │
└──────┬──────────────────────────────────────────┬───────────────┘
       │ SQL                                      │ vector
       ▼                                          ▼
┌──────────────────────┐                ┌──────────────────────┐
│  Postgres            │                │  pgvector (same PG)  │
│  · files (metadata)  │                │  · doc_chunks        │
│  · cleaning_plans    │                │  · embeddings(1536)  │
│  · processing_status │                │                      │
└──────────────────────┘                └──────────────────────┘
       ▲                                          ▲
       │ status updates                           │ embeddings written
       │                                          │
┌──────┴──────────────────────────────────────────┴───────────────┐
│  WORKER POOL  (Arq async tasks)                                 │
│  sniff schema → cached plan → polars apply → validate           │
│  → write Parquet (silver) → embed → update status               │
└──────────────────────────────┬──────────────────────────────────┘
                               ▲
                               │  pop tasks
                        ┌──────┴──────┐
                        │  Redis queue│
                        └──────▲──────┘
                               │  push task on upload
┌──────────────────────────────┴──────────────────────────────────┐
│  INGEST API  (FastAPI)                                          │
│  · POST /upload   · GET /status/{id}   · GET /files             │
└──────────────────────────────┬──────────────────────────────────┘
                               │  stream raw file
                               ▼
                        ┌──────────────┐
                        │  MinIO / S3  │
                        │  bronze/...  │
                        │  silver/...  │
                        └──────────────┘
```

## The four-store split

The same fact lives in four physical homes, each optimized for a different question.

| Store        | Job                                               | Used for                                     |
|--------------|---------------------------------------------------|----------------------------------------------|
| **S3 raw**   | Immutable source of truth                         | Replay, audit, original artifacts            |
| **Parquet**  | Columnar analytics over millions of rows          | "Avg CPM by vertical?" via DuckDB            |
| **Postgres** | Transactional state (ACID, sub-10ms lookups)      | File status, jobs, users, plans              |
| **pgvector** | Semantic search (1536-dim embeddings)             | "Find files like…", RAG over playbooks       |

If you can write a SQL `WHERE` clause, don't embed it.

## Run locally

```bash
docker-compose up --build
# in another terminal:
curl http://localhost:8000/health
curl http://localhost:8001/health
```

You should see `{"ok": true}` from each service. That's Phase 0 done.

## Status — 8-week phased build

- [x] **Phase 0** — Repo scaffolded, docker-compose stubs, CI green
- [ ] **Phase 1** — `POST /upload` → file in MinIO + row in Postgres
- [ ] **Phase 2** — Queue + worker + deterministic cleaning end-to-end
- [ ] **Phase 3** — LLM plan generation + caching + evals
- [ ] **Phase 4** — MCP server with 4 tools
- [ ] **Phase 5** — Slackbot/web UI consumer
- [ ] **Phase 6** — Observability + Grafana dashboards + polished README

Full plan: [PLAN.md](PLAN.md).

## Stack

Python 3.12, uv, FastAPI, Arq, Postgres 16 + pgvector, Redis, MinIO/S3, polars, DuckDB, FastMCP, LangGraph, Claude Sonnet 4.6 + Haiku 4.5, OpenTelemetry + Prometheus + Grafana, GitHub Actions, pytest + testcontainers.

## Development

```bash
uv sync
uv run ruff check .
uv run mypy .
uv run pytest
```
