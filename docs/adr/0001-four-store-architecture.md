# ADR 0001: Four-store data architecture

## Status
Accepted — 2026-05-24

## Context
A CSV ingestion + serving platform has to answer fundamentally different questions about the same fact:

- *"What's the current processing status of file X?"* — sub-10ms, transactional, by id
- *"What was the average CPM by vertical last quarter?"* — second-scale, over millions of rows, ad-hoc OLAP
- *"Find files that look like this one"* — approximate nearest-neighbor over high-dimensional vectors
- *"Show me the original bytes of the file uploaded at 03:14 on 2026-04-01"* — replay / audit / re-process from immutable source

No single storage engine optimizes for all four access patterns. Forcing them into one store either turns a fast point query into a slow scan, or turns an analytical aggregate into a query that locks an OLTP system, or destroys the immutability needed for audit.

## Decision
Split the same fact across four physical homes, each optimized for one access pattern:

| Store        | Engine                         | Optimized for                                              |
|--------------|--------------------------------|------------------------------------------------------------|
| **Bronze**   | S3 / MinIO (raw bytes)         | Immutable source of truth, audit, replay                   |
| **Silver**   | Parquet on S3 (columnar)       | OLAP scans via DuckDB / Athena                             |
| **Hot**      | Postgres 16                    | ACID transactional state, sub-10ms lookups by id           |
| **Vector**   | pgvector extension on same PG  | Approximate nearest-neighbor over embeddings               |

Data flows downstream: Bronze → Silver via ETL, status mirrored in Hot, summaries embedded into Vector. Bronze remains canonical.

## Consequences

**Positive:**
- Each query class is served by the engine that's actually good at it.
- Loss of a downstream store is recoverable from Bronze via re-derivation.
- Costs are bounded per tier (cold S3 < Parquet < hot PG < vector).

**Negative:**
- Four stores to operate, monitor, and back up.
- Eventual consistency between Bronze→Silver→Hot must be acknowledged in API contracts (e.g., "newly uploaded files may take seconds to appear in `GET /files`").
- The team must internalize the rule: *"if you can write a SQL `WHERE` clause, don't embed it"* — i.e., resist using vector search for filters that are exact-match SQL.

## Alternatives considered
- **One big Postgres for everything.** Rejected: row-store OLTP collapses under columnar analytical scans; storing raw bytes inflates the table and slows vacuum.
- **One data lake, no transactional DB.** Rejected: file-level status queries become full scans; concurrent writes lack ACID guarantees.
- **Dedicated vector DB (Pinecone, Weaviate).** Rejected for now — see [ADR 0005](0005-pgvector-on-same-postgres.md).
