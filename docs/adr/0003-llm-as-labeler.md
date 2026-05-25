# ADR 0003: LLM as labeler, code as worker — plan-once-per-fingerprint

## Status
Accepted — 2026-05-24

## Context
A naive CSV cleaning pipeline could invoke an LLM **once per row**: "here is a row, normalize the date, infer the schema, fill the nulls." This is the most flexible design and the most expensive one.

A back-of-envelope at production scale: 1M files × 10K rows × $0.001 per call = **$10M/year** in LLM spend. Costs scale linearly with row count, not with schema diversity. This is the wrong shape of cost curve.

The key observation: **the *plan* for cleaning a CSV depends on the source and the schema, not on the individual rows.** A million rows from the same source with the same schema should share one plan. The LLM should figure out the plan once, then deterministic code should apply it to every row.

## Decision

**The LLM is a labeler. Code is the worker.**

For each uploaded file:

1. Compute a **schema fingerprint** = `hash(source_id, sorted column names, sample column types)`.
2. Look up a cached `cleaning_plan` keyed on the fingerprint. If found → skip step 3.
3. On cache miss: call the LLM **once** to produce a structured cleaning plan (Pydantic-validated). Cache the plan under the fingerprint.
4. Apply the plan to all rows in the file using **polars**, deterministically, no LLM in the loop.

Cleaning plan fields are concrete and parametric — column renames, regex extractions, date formats, type coercions, null-fill strategies — not free-form prompts.

## Consequences

**Positive:**
- LLM cost is bounded by **schema diversity**, not row volume. Adding 100M more rows to a known source costs zero LLM calls.
- The plan is inspectable, versionable, and replayable. A reviewer can read it, evaluate it, and reject it before it touches data.
- Cleaning is deterministic. Re-running the same file produces the same Silver output.

**Negative:**
- A novel source requires an LLM call before any of its rows can be processed (cold-start latency on first file of a new fingerprint).
- The plan cache must be invalidated when the LLM model version changes, or when the cleaning DSL evolves. This requires explicit versioning of both.
- If schema fingerprints collide across genuinely different sources, plans get misapplied. The fingerprint hash function is part of the API contract.

## Cost model

| Strategy             | LLM calls per 1M rows | Approx cost |
|----------------------|-----------------------|-------------|
| LLM per row          | 1,000,000             | ~$10,000    |
| **LLM per fingerprint (this design)** | **1**     | **~$0.01**  |

Two orders of magnitude per file. At fleet scale, this is the difference between a viable business and a debt spiral.

## Alternatives considered
- **No LLM, hand-written cleaners per source.** Rejected: doesn't scale to long-tail sources; demands an engineer per new vendor.
- **LLM per row.** Rejected on cost grounds, see above.
- **LLM per file but no cache.** Rejected: the same source uploaded 1000 times pays 1000× for the same plan.
