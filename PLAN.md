# signal-ingest — Build Plan

> **Pickup-from-cold reference doc.** This is the standalone plan for the `signal-ingest` capstone project. Drop a fresh Claude into the actual repo and point it at this file (or copy it into the project as `PLAN.md`). It's self-contained — assumes zero context from prior conversations.

---

## 1. Mission

Build a **production-shaped data ingestion + serving platform** that takes messy CSVs in, applies LLM-driven schema understanding deterministically and cost-efficiently, exposes cleaned data via an MCP server, and lets a Slackbot/web UI answer natural-language questions over it.

The repo is the artifact. The artifact is the answer to *"have you ever built a system?"*

## 2. Why this project exists (the WHY, in one paragraph)

This project exists to close a real gap: being able to answer *"have you built a system?"* with code, not abstractions. Every section maps to a concrete lifecycle axis — ingestion, storage, scaling, observability — that a senior backend/AI engineer is expected to reason about end-to-end. The deliverable is a public repo, not a notebook or a slide.

**Background reading (kept private, referenced for the author):**

- four-store architecture deep-dive
- production-pipeline tooling intuition
- distributed-systems reliability/observability primer
- eval workflow

## 3. The core architectural insight — four-store split

The spine of this system is that **the same fact lives in four physical homes**, each optimized for a different question:

```
HOT  ─ Postgres + pgvector  ─ ms queries, current state, semantic search
                                ▲
                                │ feeds from
                                │
WARM ─ Parquet (Silver/Gold)   ─ second-scale, analytics, history
                                ▲
                                │ ETL'd from
                                │
COLD ─ S3 raw (Bronze)         ─ source of truth, audit, re-process
```

| Store        | Job                                               | Used for                                     |
|--------------|---------------------------------------------------|----------------------------------------------|
| **S3 raw**   | Immutable source of truth                         | Replay, audit, original artifacts            |
| **Parquet**  | Columnar analytics over millions of rows          | "Avg CPM by vertical?" via DuckDB            |
| **Postgres** | Transactional state (ACID, sub-10ms lookups)     | File status, jobs, users, plans              |
| **pgvector** | Semantic search (1536-dim embeddings)             | "Find files like…", RAG over playbooks       |

If you ever feel lost about where data should go, return to this table. **If you can write a SQL WHERE clause, don't embed it.**

## 4. Tech stack (and why)

| Layer            | Choice                              | Why                                                                 |
|------------------|-------------------------------------|---------------------------------------------------------------------|
| Language         | Python 3.12                         | Standard for AI; modern syntax (match, walrus, type hints)           |
| Package mgr      | uv                                  | Fast, lockfile, replaces pip + venv + pip-tools                      |
| API              | FastAPI                             | Async, OpenAPI auto, Pydantic-native                                |
| Validation       | Pydantic v2                         | Boundary contract enforcement; structured LLM output                 |
| Queue            | Redis + Arq                         | Simpler than Celery, async-native, one binary                        |
| Workers          | Arq (asyncio)                       | Same library as queue; no Celery ceremony                            |
| Transactional DB | Postgres 16 + Alembic               | Mature, pgvector ships as extension                                  |
| Vector DB        | pgvector (extension on same PG)     | One DB to back up; graduate to Pinecone only past 5M vectors         |
| Object store     | MinIO (local) / S3 (prod)           | S3 API compatibility; local-friendly                                 |
| Analytical query | DuckDB (local) / Athena (prod)      | Both read Parquet natively; zero-server local dev                    |
| LLM              | Claude Sonnet 4.6 + Haiku 4.5        | Sonnet for novel plans, Haiku for routine — model-routing demo       |
| Agent framework  | LangGraph                           | Explicit state machine; widely used in production agent stacks       |
| MCP              | FastMCP                             | Lightweight Python MCP server                                        |
| Observability    | OpenTelemetry + Prometheus + Grafana| OTel is industry standard; Grafana stack is free                     |
| Container        | Docker + docker-compose             | Local-first dev story; same image to prod                            |
| CI/CD            | GitHub Actions                      | Free for public repos; standard                                      |
| Tests            | pytest + httpx + testcontainers     | Real Postgres in tests, no mocks                                     |
| Format/lint      | ruff                                | One tool replaces black + isort + flake8                             |

**Pinned decisions (do not relitigate):**
- Use **real Postgres in tests** via testcontainers — never mock the DB. (`data/evals-guide.html` explains why.)
- LLM is the **labeler**, code is the **worker**. Plan caching is non-negotiable — see "100x cost trap" in the storage guide.
- **All data flows are observable.** Every service emits Prometheus metrics + OTel traces from day one, not "later."

## 5. Repo layout

```
signal-ingest/
├── README.md                  ← architecture diagram + setup
├── PLAN.md                    ← (this file, copied in)
├── docker-compose.yml         ← whole stack: PG, Redis, MinIO, services
├── pyproject.toml             ← uv, Python 3.12, ruff, pytest
├── .github/workflows/
│   └── ci.yml                 ← test + lint + type-check + build
│
├── services/
│   ├── ingest_api/            ← FastAPI (POST /upload, GET /status)
│   ├── worker/                ← Arq tasks: clean, validate, embed, write
│   ├── mcp_server/            ← FastMCP tools for downstream agents
│   └── slackbot/              ← LangGraph agent + Slack/web handler
│
├── shared/
│   ├── models/                ← Pydantic domain models (canonical schema)
│   ├── db/
│   │   ├── migrations/        ← Alembic
│   │   └── repositories/      ← typed query layer
│   └── observability/         ← OTel + Prometheus helpers
│
├── infra/
│   ├── grafana/               ← pre-built dashboards (cost, pipeline, quality)
│   ├── prometheus/
│   └── k8s/                   ← (optional, advanced) prod manifests
│
├── evals/
│   ├── datasets/              ← versioned jsonl: golden CSV examples
│   └── suites/                ← pytest suites: schema-mapping, faithfulness
│
└── tests/
    ├── integration/           ← cross-service tests with testcontainers
    └── e2e/                   ← upload → query end-to-end
```

## 6. Architecture diagram

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
│  1. Sniff schema                                                │
│  2. Lookup cached plan (by source × fingerprint)                │
│  3. If miss: LLM (Sonnet) → Pydantic-validated plan → cache     │
│  4. Apply plan with polars (deterministic, fast)                │
│  5. Validate canonical schema                                   │
│  6. Write Parquet to silver/                                    │
│  7. Embed summary → pgvector                                    │
│  8. Update PG status                                            │
└──────────────────────────────┬──────────────────────────────────┘
                               ▲
                               │  pop tasks
                               │
                        ┌──────┴──────┐
                        │  Redis queue│
                        └──────▲──────┘
                               │  push task on upload
                               │
┌──────────────────────────────┴──────────────────────────────────┐
│  INGEST API  (FastAPI)                                          │
│  · POST /upload   · GET /status/{id}   · GET /files             │
│  · auth, rate-limit, validation, OpenAPI                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │  stream raw file
                               ▼
                        ┌──────────────┐
                        │  MinIO / S3  │
                        │  bronze/...  │
                        │  silver/...  │
                        │   (Parquet)  │
                        └──────────────┘

OBSERVABILITY (cross-cutting from day one)
┌─────────────────────────────────────────────────────────────────┐
│  Prometheus metrics   ◄── every service                         │
│  OpenTelemetry traces ◄── distributed request tracing           │
│  Structured JSON logs ◄── shipped to Loki / stdout              │
│  Grafana dashboards:                                            │
│    · Pipeline health  (queue depth, latency P95, error rate)    │
│    · Data quality     (validation pass rate, eval scores)       │
│    · Cost             (LLM spend, S3 by tier, query bytes)      │
└─────────────────────────────────────────────────────────────────┘
```

## 7. 8-week phased build (10–15 hrs/week)

| Phase   | Weeks  | End state                                                                 |
|---------|--------|---------------------------------------------------------------------------|
| **0**   | Week 0 | Repo scaffolded, docker-compose stubs, public on GitHub, README drafted   |
| **1**   | 1–2    | `POST /upload` works → file in MinIO + row in Postgres                    |
| **2**   | 3–4    | Queue + worker + deterministic cleaning (no LLM yet) → end-to-end works   |
| **3**   | 5      | LLM plan generation + caching + evals → cost-disciplined cleaning         |
| **4**   | 6      | MCP server with 4 tools → queryable from any MCP client                   |
| **5**   | 7      | Slackbot (or web UI) consumer → ask question, get answer                  |
| **6**   | 8      | Observability + Grafana dashboards + polished README → demo-recordable    |

(Full per-phase task lists are tracked separately by the author.)

## 8. Week 0 — the first 2-hour PR

Do this **in order**. Don't skip ahead. The goal is *empty but well-scaffolded*. Empty + well-scaffolded > half-built mess.

```bash
# 1. Scaffold the project
mkdir -p ~/projects/signal-ingest && cd ~/projects/signal-ingest
uv init --python 3.12
uv add fastapi uvicorn pydantic[email] sqlalchemy alembic asyncpg redis arq \
       polars duckdb pgvector anthropic langgraph fastmcp httpx
uv add --dev pytest pytest-asyncio ruff mypy testcontainers[postgres,redis] httpx

# 2. Create the directory skeleton (empty files / __init__.py for now)
mkdir -p services/{ingest_api,worker,mcp_server,slackbot}
mkdir -p shared/{models,db/migrations,db/repositories,observability}
mkdir -p infra/{grafana,prometheus}
mkdir -p evals/{datasets,suites}
mkdir -p tests/{integration,e2e}

# 3. docker-compose.yml — boxes only, no logic
#    Services: postgres (with pgvector), redis, minio, ingest_api, worker, mcp_server
#    Each python service: empty stub that boots and exits 0

# 4. README.md must include from day one:
#    - 1-paragraph mission (steal from this file's section 1)
#    - The architecture diagram (steal from this file's section 6)
#    - The four-store table (steal from this file's section 3)
#    - "Run locally" — docker-compose up + curl POST /upload
#    - "Status" — checklist of the 6 phases, ☐ all unchecked

# 5. CI in .github/workflows/ci.yml
#    - uv install, ruff check, mypy, pytest (will be empty initially — fine)

# 6. Commit + push to PUBLIC GitHub repo named "signal-ingest"
#    Tag the README "Status" badge: "🚧 Phase 0 — scaffold complete"
```

**Definition of done for Week 0:** clone the repo on a fresh machine, run `docker-compose up`, see all six services boot to a healthy state. Empty endpoints return `{"ok": true}`. CI on PR is green. **That's it.** Resist the urge to add features in Week 0.

## 9. Success criteria — what "shipped" looks like

You can credibly tell this story when Phase 3 is done:

> *"I built signal-ingest — a CSV ingestion platform. FastAPI ingest service drops raw files into S3 bronze, pushes a job to Redis. Arq workers pull, sniff schema, look up a cached LLM plan keyed by source + fingerprint, apply the plan with polars deterministically — that's the 100x cost discipline, LLM as labeler not worker. Cleaned Parquet lands in silver, partitioned by date. An MCP server exposes search and SQL tools. Postgres holds operational state. pgvector — same Postgres — holds embeddings of file summaries for semantic search. Observability is OpenTelemetry + Prometheus + Grafana, with cost-per-source on the dashboard from day one. Public repo, end-to-end tests with testcontainers, GitHub Actions CI."*

You're done with this capstone when:

- [ ] All 6 phases shipped, repo public
- [ ] README has architecture diagram + four-store table + run-locally instructions
- [ ] CI is green on main; tests cover happy path + 3 failure modes
- [ ] `evals/` has 20+ labeled CSVs and a CI-gated eval suite
- [ ] Grafana dashboard screenshot in README shows live pipeline + cost
- [ ] You can demo the upload → query loop in 90 seconds
- [ ] LinkedIn post drafted + repo linked

## 10. Anti-patterns to avoid (lessons from prior projects)

- ❌ **Don't mock the database in tests.** Use testcontainers — mocked tests can pass while real migrations break.
- ❌ **Don't add features in Phase 0.** Scaffold first. Empty repo with green CI > half-built mess.
- ❌ **Don't embed cleaned tabular data into pgvector.** That's a SQL question wearing a vector hat.
- ❌ **Don't skip observability until "later."** "Later" never comes. Bake it in from Phase 1.
- ❌ **Don't run the LLM per row.** Plan-once-per-fingerprint or you'll spend $1.5M/year hypothetically.
- ❌ **Don't write a comment for what code already says.** Names do that work.
- ❌ **Don't write multi-line docstrings.** One short line max.

## 11. When stuck

- Architecture confusion → revisit the four-store table in section 3 ("if it has a SQL `WHERE`, don't embed it")
- Tool intuition → re-read section 4's stack rationale
- Reliability/resilience → return to the observability layer in section 6
- Eval design → see Phase 3 in section 7

## 12. One-line takeaway

**Build the system end-to-end. Public repo. Four stores, six phases, eight weeks. The artifact is the answer.**
