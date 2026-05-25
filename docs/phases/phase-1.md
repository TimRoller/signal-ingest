# Phase 1 — Ingest

> **Goal:** A client `POST`s a CSV; the bytes land in MinIO bronze, a row lands in Postgres, and the caller gets back a stable `file_id` they can poll on.

Phase 0 proved the boxes boot. Phase 1 makes one of them do real work.

## Definition of done

| Check                                                                                                                                  | How to verify                                                          |
|----------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| `curl -F 'file=@sample.csv' -F 'source=demo' http://localhost:8000/upload` returns 201 with `{file_id, status, sha256, byte_size, s3_uri}` | Manual + integration test                                              |
| The same upload repeated returns 200 with the same `file_id` (no duplicate row, no duplicate object)                                  | Integration test `test_upload_is_idempotent_on_source_plus_sha256`     |
| `GET /files?limit=10&offset=0` paginates rows ordered by `created_at DESC`                                                             | Integration test                                                       |
| `GET /status/{file_id}` returns the row or 404                                                                                         | Integration test                                                       |
| Prometheus metrics scrape-able from `GET /metrics`                                                                                     | `curl http://localhost:8000/metrics \| grep http_requests_total`        |
| Alembic migration applies cleanly to a fresh database                                                                                  | `alembic upgrade head` against a clean testcontainer                   |
| Integration test runs against real Postgres + real MinIO via testcontainers; passes in CI                                              | GitHub Actions `ci` job green                                          |

## Data model

### Table: `files`

```sql
CREATE TYPE file_status AS ENUM ('received', 'processing', 'cleaned', 'failed');

CREATE TABLE files (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT        NOT NULL,
    original_name   TEXT        NOT NULL,
    sha256          CHAR(64)    NOT NULL,
    byte_size       BIGINT      NOT NULL CHECK (byte_size >= 0),
    s3_uri          TEXT        NOT NULL,
    status          file_status NOT NULL DEFAULT 'received',
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT files_source_sha256_key UNIQUE (source, sha256)
);

CREATE INDEX files_created_at_desc_idx ON files (created_at DESC);
CREATE INDEX files_status_idx          ON files (status);
```

**Notes:**

- `source` is a free-form string for now (`"demo"`, `"vendor_a"`); a future migration will tighten this into an FK once sources are first-class.
- `(source, sha256)` is the idempotency key. Identical bytes from the same source are treated as the same upload.
- `gen_random_uuid()` requires `pgcrypto`. The migration enables it.
- No FKs yet (no other tables). Phase 2 introduces `processing_jobs` referencing `files.id`.

### Pydantic models

`shared/models/file.py`:

```python
class FileStatus(StrEnum):
    received = "received"
    processing = "processing"
    cleaned = "cleaned"
    failed = "failed"

class FileRecord(BaseModel):
    id: UUID
    source: str
    original_name: str
    sha256: str
    byte_size: int
    s3_uri: str
    status: FileStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

`UploadResponse` and `FileListResponse` wrap `FileRecord` for the API.

## API contract

### `POST /upload`

**Request:** `multipart/form-data`

| Field        | Type   | Required | Notes                                          |
|--------------|--------|----------|------------------------------------------------|
| `file`       | file   | yes      | The CSV bytes                                  |
| `source`     | string | yes      | `^[a-z][a-z0-9_]{1,63}$`                       |

**Limits:**

- Max body size: 100 MiB (configurable via `MAX_UPLOAD_BYTES`).
- Content-Type must be `text/csv` or `application/csv` or `application/octet-stream`.

**Responses:**

| Code | Body                                                              | When                                                                   |
|------|-------------------------------------------------------------------|------------------------------------------------------------------------|
| 201  | `FileRecord`                                                       | First time these bytes from this source are seen                       |
| 200  | `FileRecord` (existing row)                                        | (source, sha256) already exists — **idempotent**                       |
| 413  | `{detail: "file too large", limit_bytes: int}`                     | Body exceeds `MAX_UPLOAD_BYTES`                                        |
| 415  | `{detail: "unsupported content-type"}`                             | Bad Content-Type                                                       |
| 422  | `{detail: "<pydantic validation error>"}`                          | Missing/malformed `source`, missing `file`                             |
| 500  | `{detail: "internal error", trace_id: "..."}`                      | Storage or DB failure not classified above                             |

### `GET /status/{file_id}`

| Code | Body         | When                       |
|------|--------------|----------------------------|
| 200  | `FileRecord` | Row exists                 |
| 404  | `{detail}`   | Not found                  |

### `GET /files?limit={1..100}&offset={>=0}&source={optional}`

| Code | Body                                       |
|------|--------------------------------------------|
| 200  | `{items: [FileRecord], total: int}`        |
| 422  | Bad pagination params                      |

Ordered by `created_at DESC`. Default `limit=20`, `offset=0`.

### `GET /metrics`

Prometheus exposition format. Includes:

- `http_requests_total{method, path, status}` (counter)
- `http_request_duration_seconds{method, path}` (histogram)
- `signal_uploads_total{source, result}` (counter; result ∈ `{created, duplicate, error}`)
- `signal_upload_bytes{source}` (histogram)

### `GET /health`

Existing Phase 0 endpoint. Unchanged: `{"ok": true}` if the process is up. **Does not** check downstream dependencies — that's `GET /ready` (deferred to a later phase).

## MinIO key convention

```
bronze/{source}/{yyyy}/{mm}/{dd}/{sha256}.csv
```

- `bronze` bucket created on app startup if missing.
- Time partition is **upload time UTC**, not any timestamp inside the file. Phase 2 (cleaning) re-partitions Silver by source-defined event time.
- Filename uses the full sha256, not the original filename. Original is preserved in `files.original_name`.
- Object metadata: `original-name`, `source`, `uploaded-by` (later, after auth).

This means the same `(source, sha256)` combo always maps to the same key — idempotent at the storage layer too, even if the DB and storage drift.

## Idempotency story

The contract: **`(source, sha256)` is the natural key.** Same bytes, same source = same file, no matter how many times uploaded.

Sequence:

1. Stream the upload, computing sha256 in chunks (8 KiB blocks). Buffer to a `SpooledTemporaryFile` (memory until 10 MiB, then disk).
2. Compute the deterministic S3 key from `(source, sha256, upload_time)`.
3. `INSERT INTO files (...) ON CONFLICT (source, sha256) DO NOTHING RETURNING *`.
4. If the INSERT returned a row → upload bytes to MinIO under the computed key → return 201 with the new row.
5. If the INSERT was a no-op (conflict) → `SELECT` the existing row → return 200 with the existing row. **Do not re-upload.** The existing s3_uri is trusted.

### Failure modes

| Failure                                        | Behavior                                                                                                                                   |
|------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| MinIO upload fails after PG INSERT             | `DELETE FROM files WHERE id = ?` (compensating undo) and return 500. Caller can retry; second attempt will INSERT cleanly.                |
| PG INSERT fails for unexpected reason          | Return 500. No MinIO write yet. Caller retries.                                                                                            |
| Client disconnects mid-stream                  | Spooled file is dropped, no INSERT, no MinIO write. No leak.                                                                               |
| Process crashes between INSERT and MinIO PUT   | DB row exists with `s3_uri` pointing to a key that doesn't exist. Detected by a future reconciler in Phase 6. Acceptable for now.         |
| Same upload retried twice in flight (race)     | One INSERT wins, the other gets the conflict path. Both clients receive the same `file_id`. Worst case: one extra MinIO PUT to the same key (S3 is idempotent on identical PUTs). |

The orphan-row case (INSERT succeeds, MinIO fails, undo also fails) is the only one not bounded by the design. Mitigation: log loudly and emit a `signal_orphan_rows_total` counter so it's visible.

## Observability hooks

`shared/observability/init.py` wires up:

- **OpenTelemetry** SDK with a console exporter (no backend wired yet; ADR 0004 says "from day one," not "with full backend from day one"). Instruments FastAPI and asyncpg automatically.
- **`prometheus-fastapi-instrumentator`** for the default HTTP metrics on `/metrics`.

In the upload handler, custom metrics:

- `signal_uploads_total.labels(source, result).inc()` — counter
- `signal_upload_bytes.labels(source).observe(byte_size)` — histogram
- A span around the MinIO upload, attributes: `source`, `byte_size`, `key`

Structured logs are JSON, single-line, include `trace_id` when present.

## Test plan

`tests/integration/test_upload.py`. Session-scoped fixtures spin up:

- A `pgvector/pgvector:pg16` container, run `alembic upgrade head` against it.
- A `minio/minio:latest` container, create the `bronze` bucket on startup.
- A `TestClient(app)` wired to those endpoints.

| Test                                                    | Assertion                                                                                  |
|---------------------------------------------------------|--------------------------------------------------------------------------------------------|
| `test_upload_happy_path`                                | 201; row exists; object exists at expected key                                              |
| `test_upload_is_idempotent_on_source_plus_sha256`        | First call 201, second call 200; same `file_id`; only one row; only one PUT (verified via spy) |
| `test_upload_rejects_oversized_body`                     | 413                                                                                         |
| `test_upload_rejects_bad_content_type`                   | 415                                                                                         |
| `test_upload_rejects_missing_source`                     | 422                                                                                         |
| `test_upload_rejects_malformed_source_pattern`           | 422                                                                                         |
| `test_get_status_returns_row`                            | 200, body matches insert                                                                    |
| `test_get_status_404_unknown_id`                         | 404                                                                                         |
| `test_get_files_pagination_and_ordering`                 | Two uploads; default order is DESC by created_at; `limit=1&offset=1` returns the second    |
| `test_metrics_endpoint_exposes_counter_after_upload`     | After one upload, `signal_uploads_total{source="demo",result="created"} 1.0`                |

Two smoke tests remain from Phase 0 (`/health`) — kept.

## What's explicitly out of scope for Phase 1

- Auth / API keys — Phase 5+ when there's a real consumer.
- File validation (column types, charset, BOM handling) — that's the worker's job in Phase 2.
- `GET /ready` deep healthcheck — when ops makes it necessary.
- Eviction / tiering between bronze and silver — Phase 2/3.
- The worker actually pulling jobs off Redis — Phase 2.
- LLM anything — Phase 3.
