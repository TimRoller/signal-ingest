# ADR 0005: pgvector on the same Postgres, not a separate vector DB

## Status
Accepted — 2026-05-24 (revisit at ~5M vectors)

## Context
The system needs approximate nearest-neighbor search over embeddings (1536-dim, OpenAI/Anthropic-compatible) for two use cases:

1. *"Find files similar to this one"* — file-summary embeddings, single-digit thousands today, low-millions long-term.
2. *"What playbook chunk best answers this question?"* — RAG over a small curated corpus.

Vector search is a real workload, but **not a high-traffic one** for this project. Both use cases are interactive (latency budget: hundreds of ms) and low-QPS (a handful per minute at peak).

Vector databases broadly fall into two camps:

| Option                    | Strength                                              | Cost                                                 |
|---------------------------|-------------------------------------------------------|------------------------------------------------------|
| **pgvector** (extension on PG) | One database to back up, one to monitor, one to migrate. SQL joins between vectors and metadata. | Slower ANN at very large N (no advanced index tuning). |
| **Pinecone / Weaviate / Milvus** | Specialized ANN indexes, billion-scale benchmarks. | Second system to back up, monitor, secure. Cross-system joins require app-layer code. |

At our current and projected scale (single-digit millions of vectors), pgvector's HNSW index is competitive enough on latency that the operational simplicity wins.

## Decision

Use **pgvector** on the same Postgres instance that holds transactional state. Embeddings live in a `doc_chunks` table with a `vector(1536)` column and an HNSW index.

We commit to **revisit this decision when total vector count exceeds ~5M** or when p95 ANN query latency exceeds 100ms despite tuning.

## Consequences

**Positive:**
- One database to operate. Backups, replication, monitoring, alerting — all reuse existing PG tooling.
- Joins between vector search results and transactional metadata are SQL, not application code (`SELECT ... FROM doc_chunks d JOIN files f USING (file_id) WHERE d.embedding <-> $1 < 0.3 AND f.status = 'ready'`).
- No second client library, no second auth surface, no second network hop.

**Negative:**
- pgvector's HNSW has fewer knobs than a purpose-built vector DB. At scale, tuning options are limited.
- Vector index build time blocks DDL on the table — large reindexes need careful scheduling.
- Postgres connection pool is shared between transactional and vector workloads — a runaway vector query can starve OLTP, so query timeouts and statement_timeout are mandatory.

## Re-evaluation criteria

Move to a dedicated vector DB **when any of the following becomes true**:

- Total vector count > 5,000,000
- p95 ANN query latency > 100ms despite HNSW tuning (`ef_search`, `m`, partitioning)
- Vector write throughput pressures OLTP write latency
- Need for hybrid search features (BM25 + vector, structured filters at index level) that pgvector cannot serve

Until then, the simpler architecture wins.

## Alternatives considered
- **Pinecone / Weaviate from day one.** Rejected as premature optimization for this scale. Adds an operational burden disproportionate to the workload.
- **In-process FAISS index loaded from disk.** Rejected: no transactional updates, no cross-process consistency, no SQL joins.
- **Postgres `cube` extension.** Rejected: pgvector is the better-maintained, better-indexed successor.
