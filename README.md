# signal-ingest

[![CI](https://github.com/TimRoller/signal-ingest/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/TimRoller/signal-ingest/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> A production-shaped data ingestion + serving platform: messy CSVs in, deterministic LLM-driven cleaning, exposed via an MCP server, queryable from a Slackbot or web UI.

**Status:** Phase 2 — worker + cleaning shipped · [v0.3.0](https://github.com/TimRoller/signal-ingest/releases) · CI green

---

## Architecture

```mermaid
flowchart TB
    UI["Slackbot / Web UI<br/>(consumer surface)"]
    ORCH["Orchestrator Agent<br/>LangGraph + Claude Sonnet"]
    MCP["MCP Server (FastMCP)<br/>search_files · get_metadata<br/>query_cleaned_data · search_by_similarity"]
    PG[("Postgres<br/>files · plans · status")]
    PGV[("pgvector<br/>doc_chunks · embeddings(1536)<br/>same PG instance")]
    API["Ingest API (FastAPI)<br/>POST /upload · GET /status · GET /files"]
    Q["Redis queue"]
    W["Worker Pool (Arq)<br/>sniff → cached plan → polars<br/>→ validate → Parquet → embed"]
    S3[("MinIO / S3<br/>bronze (raw) · silver (Parquet)")]
    OBS["Observability<br/>OTel + Prometheus + Grafana"]

    UI -->|natural-language query| ORCH
    ORCH -->|MCP stdio/HTTP| MCP
    MCP -->|SQL| PG
    MCP -->|vector search| PGV

    API -->|stream raw| S3
    API -->|enqueue job| Q
    Q -->|pop task| W
    W -->|write Parquet| S3
    W -->|embed summary| PGV
    W -->|update status| PG

    OBS -.->|metrics + traces| API
    OBS -.-> W
    OBS -.-> MCP
```

## The four-store split

The same fact lives in four physical homes, each optimized for a different question. ([ADR 0001](docs/adr/0001-four-store-architecture.md))

| Store        | Job                                               | Used for                                     |
|--------------|---------------------------------------------------|----------------------------------------------|
| **S3 raw**   | Immutable source of truth                         | Replay, audit, original artifacts            |
| **Parquet**  | Columnar analytics over millions of rows          | "Avg CPM by vertical?" via DuckDB            |
| **Postgres** | Transactional state (ACID, sub-10ms lookups)      | File status, jobs, users, plans              |
| **pgvector** | Semantic search (1536-dim embeddings)             | "Find files like…", RAG over playbooks       |

If you can write a SQL `WHERE` clause, don't embed it.

## Why these choices

Short, durable decision records — what was chosen and what we accept by choosing it:

- [ADR 0001 — Four-store data architecture](docs/adr/0001-four-store-architecture.md)
- [ADR 0002 — Real Postgres in tests via testcontainers, not mocks](docs/adr/0002-testcontainers-not-mocks.md)
- [ADR 0003 — LLM as labeler, code as worker — plan-once-per-fingerprint](docs/adr/0003-llm-as-labeler.md)
- [ADR 0004 — Observability from day one, not "later"](docs/adr/0004-observability-from-day-one.md)
- [ADR 0005 — pgvector on the same Postgres, not a separate vector DB](docs/adr/0005-pgvector-on-same-postgres.md)

## Run locally

```bash
docker compose up -d --build

# upload a CSV — worker picks it up and cleans it within ~1s
echo "id,name,value" > sample.csv
echo "1,  alpha  ,10"    >> sample.csv
curl -F 'file=@sample.csv;type=text/csv' -F 'source=demo' http://localhost:8000/upload
# → {"file": {"id": "...", "status": "received", ...}, "duplicate": false}

# poll status — flips to "cleaned" once the worker finishes
curl http://localhost:8000/status/{file_id}
# → {"id": "...", "status": "cleaned", ...}

# reprocess (idempotent — silver Parquet overwritten)
curl -X POST http://localhost:8000/reprocess/{file_id}

# metrics
curl http://localhost:8000/metrics | grep signal_uploads_total      # ingest API
curl http://localhost:9100/metrics | grep signal_cleaned_total      # worker

docker compose down
```

Six services boot: `postgres` (with pgvector), `redis`, `minio`, `ingest_api`, `mcp_server`, `worker`. The `ingest_api` runs `alembic upgrade head` before serving.

## Status — 8-week phased build

- [x] **Phase 0** — Repo scaffolded, docker-compose verified, CI green
- [x] **Phase 1** — `POST /upload` → file in MinIO + row in Postgres
- [x] **Phase 2** — Queue + worker + deterministic cleaning end-to-end
- [ ] **Phase 3** — LLM plan generation + caching + evals (next)
- [ ] **Phase 3** — LLM plan generation + caching + evals
- [ ] **Phase 4** — MCP server with 4 tools
- [ ] **Phase 5** — Slackbot / web UI consumer
- [ ] **Phase 6** — Observability + Grafana dashboards + polished README

Full plan: [PLAN.md](PLAN.md). Changelog: [CHANGELOG.md](CHANGELOG.md).

## Stack

Python 3.12 · uv · FastAPI · Arq · Postgres 16 + pgvector · Redis · MinIO/S3 · polars · DuckDB · FastMCP · LangGraph · Claude Sonnet 4.6 + Haiku 4.5 · OpenTelemetry + Prometheus + Grafana · GitHub Actions · pytest + testcontainers.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy services shared
uv run pytest
```

## License

[MIT](LICENSE).
