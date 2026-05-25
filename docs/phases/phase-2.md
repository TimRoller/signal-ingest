# Phase 2 — Queue + worker + deterministic cleaning

> **Goal:** An uploaded CSV gets picked up by a worker, run through a *hard-coded* per-source cleaning plan, written to silver as Parquet, and its `files.status` flips to `cleaned`. No LLM yet — Phase 3 swaps in LLM-generated plans on top of this exact plumbing.

This phase turns the repo from "ingest sink" into "actual pipeline." It also *defines the boundary* the LLM will plug into later, which is more important than the cleaning itself.

## Definition of done

| Check                                                                                                                | How to verify                                              |
|----------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------|
| Upload demo CSV → within ~2 s, `GET /status/{file_id}` shows `status: "cleaned"`                                     | Manual + integration test                                  |
| Parquet exists at `silver/{source}/{yyyy}/{mm}/{dd}/{file_id}.parquet`, readable by DuckDB                           | Integration test                                           |
| `processing_jobs` row records the run: status `queued → running → cleaned` (or `failed` with `last_error`) + attempts | Integration test                                           |
| Re-running the same `file_id` is idempotent — silver Parquet is overwritten, status stays `cleaned`, no orphan rows | Integration test                                           |
| Invalid CSV → status `failed`, `error_message` populated, no Parquet written                                          | Integration test                                           |
| `POST /reprocess/{file_id}` re-enqueues a previously processed file                                                  | Integration test                                           |
| `signal_cleaned_total{source, result}`, `signal_cleaning_duration_seconds{source}`, `signal_rows_processed{source}` on `/metrics` | curl + integration test                          |
| All tests green (Phase 0 smoke + Phase 1 integration + Phase 2 unit + Phase 2 integration) in CI                     | GitHub Actions ci.yml                                      |

## New components

```
shared/
├── cleaning/                   ← NEW
│   ├── operations.py           ← typed cleaning ops (Pydantic discriminated union)
│   ├── plan.py                 ← CleaningPlan model
│   ├── apply.py                ← pure (plan, df) → df
│   └── registry.py             ← source → CleaningPlan (Phase 2 hand-coded; Phase 3 fills via LLM)
└── db/repositories/
    └── processing_jobs.py      ← NEW

services/
├── ingest_api/
│   └── (POST /reprocess, enqueue on upload)
└── worker/
    └── main.py                 ← Arq worker; clean_file(file_id) task
```

## Data model

### Table: `processing_jobs`

```sql
CREATE TYPE job_status AS ENUM ('queued', 'running', 'cleaned', 'failed');

CREATE TABLE processing_jobs (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id       UUID        NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    status        job_status  NOT NULL DEFAULT 'queued',
    attempts      INTEGER     NOT NULL DEFAULT 0,
    last_error    TEXT,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX processing_jobs_file_id_idx ON processing_jobs (file_id);
CREATE INDEX processing_jobs_status_idx  ON processing_jobs (status);
```

One row per processing attempt cycle (not per individual retry — the `attempts` counter tracks retries within a single job).

### Cleaning plan model

A cleaning plan is a list of typed operations. Pydantic discriminated union — each op has a `kind` discriminator and its own validated fields.

```python
class RenameColumn(BaseModel):
    kind: Literal["rename"]
    from_: str = Field(alias="from")
    to: str

class CoerceType(BaseModel):
    kind: Literal["coerce_type"]
    column: str
    to: Literal["int", "float", "bool", "string", "date", "datetime"]

class ParseDate(BaseModel):
    kind: Literal["parse_date"]
    column: str
    format: str  # strptime format string

class DropNulls(BaseModel):
    kind: Literal["drop_nulls"]
    columns: list[str]

class FillNull(BaseModel):
    kind: Literal["fill_null"]
    column: str
    value: str | int | float | bool

class Trim(BaseModel):
    kind: Literal["trim"]
    column: str

class Lowercase(BaseModel):
    kind: Literal["lowercase"]
    column: str

Operation = Annotated[
    RenameColumn | CoerceType | ParseDate | DropNulls | FillNull | Trim | Lowercase,
    Field(discriminator="kind"),
]

class CleaningPlan(BaseModel):
    version: str  # of the plan grammar — bump when ops are added/removed
    source: str
    operations: list[Operation]
```

**Why discriminated union, not free-form prompt strings:** Phase 3's LLM emits exactly this shape and it gets validated before a single byte of data is touched. Bad plans never reach the applier. This is the ADR 0003 contract: *LLM is labeler, code is worker.*

### The applier

`shared/cleaning/apply.py`:

```python
def apply(plan: CleaningPlan, df: pl.DataFrame) -> pl.DataFrame:
    for op in plan.operations:
        match op:
            case RenameColumn(from_=src, to=dst):
                df = df.rename({src: dst})
            case CoerceType(column=c, to="int"):
                df = df.with_columns(pl.col(c).cast(pl.Int64, strict=False))
            # ... etc
    return df
```

**Pure function.** No I/O, no logging, no metrics. Trivially unit-testable without containers, deterministic, replayable.

### Per-source registry

`shared/cleaning/registry.py`:

```python
PLANS: dict[str, CleaningPlan] = {
    "demo": CleaningPlan(
        version="2026-05-24",
        source="demo",
        operations=[
            Trim(kind="trim", column="name"),
            CoerceType(kind="coerce_type", column="value", to="int"),
            DropNulls(kind="drop_nulls", columns=["id"]),
        ],
    ),
    "vendor_a": CleaningPlan(
        version="2026-05-24",
        source="vendor_a",
        operations=[
            RenameColumn(kind="rename", **{"from": "TS", "to": "timestamp"}),
            ParseDate(kind="parse_date", column="timestamp", format="%Y-%m-%d %H:%M:%S"),
            Lowercase(kind="lowercase", column="vertical"),
            FillNull(kind="fill_null", column="impressions", value=0),
        ],
    ),
}

def get_plan(source: str) -> CleaningPlan | None:
    return PLANS.get(source)
```

Phase 3 will replace `PLANS` with a fingerprint-keyed cache that the LLM populates on miss. The applier and worker never need to change.

## Worker

### Arq task

`services/worker/main.py`:

```python
async def clean_file(ctx: dict, file_id: str) -> None:
    # 1. mark job 'running' (insert or update)
    # 2. fetch file row from PG
    # 3. resolve plan via registry; if missing → fail permanently with "no plan for source"
    # 4. download bronze object to bytes
    # 5. polars.read_csv(bytes)
    # 6. apply(plan, df)
    # 7. write Parquet to silver/{source}/.../{file_id}.parquet
    # 8. update files.status='cleaned', processing_jobs.status='cleaned'
    # On exception classified as transient → raise to let Arq retry (with backoff)
    # On permanent (PermanentCleaningError) → set status='failed' + last_error, do not retry
```

### Job lifecycle

```
enqueue ─→ queued ─→ running ─→ cleaned   (happy path)
                    ╲
                     ╲→ running ─→ failed (permanent — no retry)
                    ╲
                     ╲→ running ─→ queued (transient — Arq backoff retry)
```

### Concurrency

Arq default: 10 concurrent tasks per worker process. Tunable via `MAX_CONCURRENT_JOBS` env. Phase 2 ships the default; Phase 6 may add per-source rate limits.

## Retry policy

Two error classes distinguish behavior:

```python
class TransientCleaningError(Exception):
    """Re-raise to let Arq retry with backoff."""

class PermanentCleaningError(Exception):
    """Worker marks job + file as failed; no retry."""
```

| Cause                                | Class                   | Why                                     |
|--------------------------------------|-------------------------|-----------------------------------------|
| MinIO 5xx, network timeouts          | `TransientCleaningError` | retryable; likely resolves              |
| Postgres deadlock                     | `TransientCleaningError` | retryable                               |
| No plan registered for source         | `PermanentCleaningError` | not a code-level fix without new plan   |
| CSV parse failure (binary, wrong fmt) | `PermanentCleaningError` | file is genuinely bad                   |
| Plan validation against op grammar    | `PermanentCleaningError` | plan registry corruption                |
| Polars schema mismatch                | `PermanentCleaningError` | data shape doesn't match plan           |

Arq retries: `max_tries=5`, exponential backoff via `arq.cron.cron` defaults. Permanent error short-circuits via `raise Retry(defer=None)` style → no, we raise a non-`Retry` exception with a sentinel that the worker's job-coordinator catches and marks `status='failed'` *before* Arq's retry kicks in. Cleaner approach: catch `PermanentCleaningError` inside `clean_file` and update state without re-raising; only let transient ones propagate.

## Idempotency

- **Silver Parquet key is deterministic on `file_id`** → `silver/{source}/{yyyy}/{mm}/{dd}/{file_id}.parquet`. Date comes from `files.created_at` (UTC), so re-runs always overwrite the same key.
- **Re-running a job** → upserts `processing_jobs.file_id`, increments `attempts`, writes a fresh Parquet (overwrite), resets status.
- **`POST /reprocess/{file_id}`** → finds (or creates) a `processing_jobs` row, resets to `queued`, enqueues. Returns 200.

## Observability

```python
SIGNAL_CLEANED_TOTAL = Counter(
    "signal_cleaned_total",
    "File cleaning attempts by source and result",
    labelnames=("source", "result"),  # result: "cleaned" / "failed_permanent" / "failed_transient"
)

SIGNAL_CLEANING_DURATION = Histogram(
    "signal_cleaning_duration_seconds",
    "Wall time of clean_file task",
    labelnames=("source",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

SIGNAL_ROWS_PROCESSED = Histogram(
    "signal_rows_processed",
    "Row count of cleaned files",
    labelnames=("source",),
    buckets=(10, 100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000),
)
```

OTel span `worker.clean_file` wraps the task body. Attributes: `file_id`, `source`, `plan.version`, `rows_in`, `rows_out`, `byte_size_in`, `byte_size_out`. Trace context propagates from API → Redis (via Arq job kwargs) → worker (re-extracted in the task).

Worker exposes `/metrics` on port 9100 (Prometheus scrape target). Phase 6 may add a dedicated worker dashboard.

## Test plan

### Unit tests — `tests/unit/test_cleaning_apply.py`

Pure tests against the applier. No containers, no I/O. Each op gets a focused test:

| Test                                          | Input → Output                                                                |
|-----------------------------------------------|-------------------------------------------------------------------------------|
| `test_rename_column`                          | `[{"a": 1}]` + rename(a→b) → `[{"b": 1}]`                                     |
| `test_coerce_type_int_strict_false_drops_bad` | `[{"x": "10"}, {"x": "junk"}]` + coerce(x→int) → x=10 and x=null              |
| `test_parse_date_iso`                         | `[{"d": "2026-01-15"}]` + parse_date → date col                                |
| `test_drop_nulls`                             | rows with null in `id` are dropped                                            |
| `test_fill_null_scalar`                       | nulls in `impressions` become 0                                                |
| `test_trim_and_lowercase`                     | trims whitespace, lowercases                                                  |
| `test_full_plan_demo_fixture`                 | apply the `demo` plan to a synthetic frame and assert exact output            |
| `test_full_plan_vendor_a_fixture`             | apply `vendor_a` plan                                                          |
| `test_unknown_op_raises_permanent_error`      | (defense — discriminator should make this unreachable, but assert anyway)     |

### Integration tests — `tests/integration/test_worker.py`

`testcontainers` spins up Postgres, Redis, and MinIO. Worker is run in-process via `arq.Worker.async_run()`.

| Test                                                     | Assertion                                                                |
|----------------------------------------------------------|--------------------------------------------------------------------------|
| `test_upload_triggers_clean_to_completion`               | Upload `demo` CSV → wait → `files.status='cleaned'`; silver Parquet exists |
| `test_silver_parquet_is_readable_via_duckdb`             | DuckDB reads back the file; row count + column types match expectations  |
| `test_reprocess_is_idempotent`                           | POST /reprocess → job re-runs, silver overwritten, no orphan PG rows     |
| `test_missing_plan_marks_file_failed_permanently`        | Upload with source `unknown_source` → status `failed`, error in PG       |
| `test_invalid_csv_marks_file_failed_permanently`         | Upload bytes that aren't CSV → status `failed`                            |
| `test_processing_jobs_row_records_attempts_and_timing`   | After clean, `processing_jobs.attempts >= 1`, `finished_at` set           |
| `test_metrics_counter_exposes_cleaned_after_run`         | `signal_cleaned_total{source="demo",result="cleaned"} >= 1`               |

## What's explicitly out of scope for Phase 2

- **No LLM.** Plans are hand-coded in the registry. Phase 3 introduces LLM plan generation + fingerprint caching.
- **No evals.** Plans aren't evaluated; they're trusted. Phase 3 adds the eval suite that gates LLM-generated plans.
- **No MCP-layer queries against silver.** Phase 4 builds the MCP tools.
- **No backpressure / rate limiting.** Worker uses Arq defaults.
- **No data lineage / provenance.** A row in `processing_jobs` is the trail, not a full lineage graph. Phase 6 may add OpenLineage if needed.

## Risks & mitigations

| Risk                                                                        | Mitigation                                                                          |
|-----------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| OTel trace context doesn't auto-propagate through Arq                       | Manually attach `traceparent` to job kwargs in enqueue; re-attach in `clean_file`   |
| Polars + Pydantic round-trip is awkward                                     | Validate per-column types post-apply via `df.schema`; skip full row-by-row Pydantic for speed |
| Arq's `pool` API drift between minor versions                                | Pin `arq>=0.28,<0.30` in pyproject; integration test catches breakage               |
| Worker integration test needs Redis container in CI                          | testcontainers handles it; ~5–10s overhead per run                                  |
| Phase 3 LLM-generated plans might emit unknown op `kind`                    | Pydantic discriminator already rejects unknown variants; LLM gets `422` and retries |
