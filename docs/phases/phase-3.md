# Phase 3 — LLM plan generation + fingerprint cache + evals

> **Goal:** Replace the hand-coded plan registry with **LLM-generated `CleaningPlan`s, cached in Postgres by schema fingerprint, gated by an eval suite.** The applier, the worker, and the storage layer don't change. The Pydantic `CleaningPlan` discriminated union from Phase 2 is the LLM's exact output contract.

This is the phase where the project earns the *AI-engineering* label. Everything before this was plumbing in front of a hand-coded function. After this, the system reasons about new data shapes it has never seen, and an eval suite gates which plans are allowed to touch real data.

## The 100× cost insight (the whole reason for this phase)

A naive design would call the LLM **per row**:

| Strategy                              | LLM calls per 1M rows | Approx Anthropic cost |
|---------------------------------------|-----------------------|-----------------------|
| LLM per row                           | 1,000,000             | ~$10,000              |
| **LLM per fingerprint (this design)** | **1**                 | **~$0.01**            |

Two orders of magnitude **per file**. At fleet scale, this is the difference between a product that ships and one that gets killed in a budget review.

The mechanism: the plan depends on the *schema*, not the *rows*. Identical schemas share one plan; that plan applies deterministically to every row.

## Definition of done

| Check                                                                                                                                | How to verify                                                          |
|--------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| Upload CSV from a **new** source (no hand-coded plan) → worker calls LLM → plan validated → file cleans successfully                  | Integration test with a mock LLM client; manual smoke against real API |
| Re-upload identical schema (different rows OK) → cache hit, **no LLM call**                                                          | `signal_llm_calls_total` does not increment; assertion in test         |
| Eval suite runs in CI: ≥10 golden CSVs + ≥3 failure-mode CSVs; score gate ≥0.90 to merge                                            | GitHub Actions step + threshold check                                  |
| `signal_llm_cost_usd{model, source}` counter tracks spend per call                                                                   | curl `/metrics` after upload                                           |
| Bad LLM output (invalid op grammar, references nonexistent column, etc.) is **rejected before touching data** — file → `failed`     | Integration test with a mock that emits bad JSON                       |
| `cleaning_plans` table stores `(source, fingerprint, plan_json, model, created_at)`; cache hit reads, cache miss writes              | Repository tests + integration test                                    |
| All tests green: Phase 0 smoke + Phase 1 + Phase 2 + Phase 3 unit + integration + eval                                              | CI ci.yml                                                              |

## Architecture — where the LLM plugs in

```
┌─────────────────────────────┐
│  Worker.clean_file(file_id) │
└────────────┬────────────────┘
             │
             ▼
┌───────────────────────────────────────────────────┐
│  shared/cleaning/registry.get_plan(source, df)    │
│  ──────────────────────────────────────────────   │
│  1. fingerprint = fp(source, df.columns, df.dtypes, _PLAN_VERSION)  │
│  2. plan = cache.get(source, fingerprint)         │
│  3. if plan is None:                              │
│       sample = df.head(20)                        │
│       plan  = llm.generate(source, sample)        │
│       validate_plan_against_df(plan, df)          │
│       cache.put(source, fingerprint, plan)        │
│  4. return plan                                   │
└───────────────────────────────────────────────────┘
             │
             ▼
┌───────────────────────────────────────────────────┐
│  apply(plan, df)  ← unchanged from Phase 2        │
└───────────────────────────────────────────────────┘
```

Three new boundaries to lock down:

1. **`llm.generate`** — Anthropic SDK call. Uses **tool use** to force structured `CleaningPlan` output (no JSON parsing of free-form text).
2. **`validate_plan_against_df`** — runs *before* `apply`. Catches "plan references column that doesn't exist" or "coerce_type uses unknown type" without burning data.
3. **`cache.get / cache.put`** — Postgres-backed via a `cleaning_plans` table.

## Tool use vs JSON mode — decision: **tool use**

Anthropic supports both:

| Approach    | What it is                                                  | Pros                          | Cons                          |
|-------------|-------------------------------------------------------------|-------------------------------|-------------------------------|
| JSON mode   | Prompt asks for JSON; SDK enforces JSON-valid output        | Simple                        | Schema lives in the prompt; LLM can still emit any JSON shape; we'd parse + validate ourselves |
| **Tool use** | Define `submit_cleaning_plan` tool with strict JSON schema; LLM calls the tool | Schema enforced by Anthropic API; the LLM literally cannot return free-form text; matches production patterns | Slightly more SDK ceremony   |

**Decision: tool use.** The cost of "LLM returned malformed JSON" is non-recoverable here; tool use eliminates it. The tool schema is auto-derived from the `CleaningPlan` Pydantic model via `model_json_schema()`.

Shape:

```python
async def generate(source: str, sample: pl.DataFrame) -> CleaningPlan:
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        tools=[{
            "name": "submit_cleaning_plan",
            "description": "Emit a CleaningPlan to normalize the sample data.",
            "input_schema": CleaningPlan.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "submit_cleaning_plan"},  # force the tool
        messages=[{"role": "user", "content": _build_prompt(source, sample)}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    return CleaningPlan.model_validate(tool_use.input)
```

`tool_choice` *forces* the LLM to invoke the tool. The Pydantic validation at the end is belt-and-suspenders.

## Data model

### Table: `cleaning_plans`

```sql
CREATE TABLE cleaning_plans (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source        TEXT        NOT NULL,
    fingerprint   CHAR(64)    NOT NULL,         -- sha256 hex
    plan_version  TEXT        NOT NULL,         -- the _PLAN_VERSION string
    plan_json     JSONB       NOT NULL,         -- the full CleaningPlan
    model         TEXT        NOT NULL,         -- e.g. "claude-sonnet-4-6"
    input_tokens  INTEGER     NOT NULL,
    output_tokens INTEGER     NOT NULL,
    cost_usd      NUMERIC(10, 6) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (source, fingerprint, plan_version)
);

CREATE INDEX cleaning_plans_source_idx ON cleaning_plans (source);
```

Migration `0003_cleaning_plans`.

### Fingerprint function

```python
def fingerprint(source: str, columns: list[str], dtypes: list[str], plan_version: str) -> str:
    payload = json.dumps(
        {
            "source": source,
            "columns": sorted(columns),
            "dtypes": [d for _, d in sorted(zip(columns, dtypes, strict=True))],
            "plan_version": plan_version,
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

**Critical decisions:**

- **Columns are sorted** → same schema in different order = same fingerprint.
- **Dtypes are paired with columns** → adding a column with a different dtype changes the fingerprint correctly.
- **`plan_version` is included** → when the op grammar changes (e.g., a new operation type is added), old plans are automatically *not* cache hits. This is how we invalidate without a migration.

## Cache flow

```python
async def get_plan(source: str, df: pl.DataFrame, *, llm, cache) -> CleaningPlan:
    fp = fingerprint(source, df.columns, [str(d) for d in df.dtypes], _PLAN_VERSION)

    cached = await cache.get(source=source, fingerprint=fp, plan_version=_PLAN_VERSION)
    if cached is not None:
        CACHE_HITS.labels(source=source).inc()
        return cached.plan

    CACHE_MISSES.labels(source=source).inc()
    sample = df.head(20)
    plan, usage = await llm.generate(source, sample)
    _validate_plan_against_df(plan, df)  # raises PermanentCleaningError on mismatch

    await cache.put(
        source=source,
        fingerprint=fp,
        plan=plan,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
    )
    LLM_CALLS_TOTAL.labels(source=source, model=usage.model).inc()
    LLM_COST_USD.labels(source=source, model=usage.model).inc(usage.cost_usd)
    return plan
```

`_validate_plan_against_df` checks:
- Every column referenced by a `rename` / `coerce_type` / `parse_date` / `fill_null` / `trim` / `lowercase` / `drop_nulls` op exists in the df.
- No operation references a column that's both the source of a rename and the target of a later op.
- Plan version matches `_PLAN_VERSION`.

These are catches for *plausibly-valid* LLM output that wouldn't be safe to apply.

## Mock vs real LLM in CI

CI **does not** call the real Anthropic API. Three reasons:

1. **Cost** — every PR run would burn tokens. Multiply by every push.
2. **Determinism** — LLM output varies. Integration tests need to be deterministic.
3. **Network** — CI runners shouldn't depend on external APIs being up.

Strategy:

- **`PlanGenerator` is a Protocol.** Production wires `AnthropicPlanGenerator`. Tests wire `MockPlanGenerator(canned_plans: dict[source, CleaningPlan])`.
- **Eval suite** (separate from integration tests) runs against the **real API** in a nightly GitHub Actions job (not on every PR). Budget-capped via `ANTHROPIC_MAX_TOKENS_PER_RUN` env.
- **Manual smoke**: a `scripts/smoke_llm_plan.py` lets the developer call the real API end-to-end locally with an `ANTHROPIC_API_KEY` env.

This keeps the PR feedback loop cheap and fast while still exercising the real API on a regular cadence.

## Eval suite

The eval suite is what stops a regression-flavored LLM update from quietly degrading the system.

### Layout

```
evals/
├── datasets/
│   ├── happy/                       ← schema → expected canonical output
│   │   ├── marketing_metrics_v1.csv
│   │   ├── marketing_metrics_v1.expected.parquet
│   │   ├── ecommerce_orders_v1.csv
│   │   └── ecommerce_orders_v1.expected.parquet
│   │   ...
│   └── failure_modes/               ← schemas that should fail validation
│       ├── empty.csv
│       ├── binary.csv
│       └── inconsistent_columns.csv
└── suites/
    ├── conftest.py                  ← shared fixtures
    ├── test_plan_grading.py         ← gradient scoring against expected output
    └── test_failure_modes.py        ← assert each bad input → status="failed"
```

### Scoring rubric

For each golden dataset:

1. Run the **real** Anthropic API: `plan = await llm.generate(source, df)`.
2. Validate the plan structurally (column refs, type targets).
3. Apply the plan: `cleaned = apply(plan, df)`.
4. Compare `cleaned` against the expected Parquet:
   - **Schema match** (column names + dtypes): 0.5 weight
   - **Cell-level equality**: 0.5 weight
   - Score = weighted match ratio in `[0, 1]`.

Eval pass criterion: **mean score ≥ 0.90** across all happy datasets, AND **every failure-mode dataset correctly fails**.

### CI gating

- **PR CI**: runs unit + integration tests with mocked LLM. Fast (~30s overhead vs Phase 2).
- **Nightly CI** (new): runs the eval suite against the real API. Posts results to a `evals-results` branch. If score drops below threshold, opens an issue.
- **Release CI**: tags `vX.Y.0` require a green nightly within the last 24h.

### What the eval suite is *not*

It's not "did the LLM say the right thing word-for-word." It's **"did the LLM's plan produce the right cleaned output."** This is the only test that matters in production: data is right or wrong.

## Model routing — decision: **Sonnet-only for now**

The plan considered Sonnet 4.6 for novel/complex schemas and Haiku 4.5 for retries on simpler shapes. **Deferred.** Phase 3 ships Sonnet-only because:

1. Per-fingerprint, the call happens **once**. Total LLM spend over a year for ~100K distinct sources ≈ $1000 — not a meaningful cost-vs-quality tradeoff yet.
2. Premature optimization: routing rules become wrong as schemas evolve; better to have a real cost dataset before routing.
3. Adds testing surface (two code paths to mock).

Model routing comes back in Phase 6 with real cost data behind it.

## Observability

New metrics (worker `/metrics` on port 9100):

```python
LLM_CALLS_TOTAL = Counter(
    "signal_llm_calls_total",
    "LLM plan-generation calls",
    labelnames=("source", "model", "result"),  # result: "ok" / "validation_failed" / "api_error"
)

LLM_COST_USD = Counter(
    "signal_llm_cost_usd",
    "Cumulative LLM spend in USD",
    labelnames=("source", "model"),
)

LLM_LATENCY_SECONDS = Histogram(
    "signal_llm_latency_seconds",
    "Anthropic API call wall time",
    labelnames=("model",),
    buckets=(0.25, 0.5, 1, 2, 5, 10, 30),
)

CACHE_HITS = Counter("signal_plan_cache_hits_total", "...", labelnames=("source",))
CACHE_MISSES = Counter("signal_plan_cache_misses_total", "...", labelnames=("source",))
```

Cost is computed via a small per-model pricing table (`shared/llm/pricing.py`):

```python
PRICING_PER_1M_TOKENS = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5":  {"input": 1.0, "output": 5.0},
}
```

OTel span `llm.generate_plan` wraps the API call. Attributes: `source`, `model`, `input_tokens`, `output_tokens`, `cost_usd`.

## Test plan

### Unit tests
- `test_fingerprint.py` — same schema (different column order) → same fingerprint; different dtype → different fingerprint; `_PLAN_VERSION` bump → different fingerprint.
- `test_plan_validation.py` — plan referencing nonexistent column → raises `PermanentCleaningError`; valid plan passes.
- `test_pricing.py` — token counts → USD computation correct for each model.

### Integration tests (mocked LLM)
- `test_new_source_triggers_llm_then_caches.py` — upload novel source → mock LLM returns canned plan → file cleans, `cleaning_plans` row inserted; re-upload same schema → no LLM call, cache hit metric increments.
- `test_bad_llm_output_marks_file_failed.py` — mock LLM returns plan referencing nonexistent column → file → status="failed", no Parquet written.
- `test_cache_invalidation_on_plan_version_bump.py` — bump `_PLAN_VERSION`, re-upload same data → cache miss → LLM called again.

### Eval suite (real LLM, nightly)
- ≥10 golden datasets across realistic source shapes (timestamp parsing, currency, null handling, etc.).
- ≥3 failure-mode datasets (empty, binary, malformed).
- Score ≥0.90 mean across happy datasets.

## What's explicitly out of scope for Phase 3

- **Model routing logic.** Sonnet-only. Phase 6.
- **Plan re-generation / drift detection.** Once cached, plans don't get re-run unless `_PLAN_VERSION` changes. Phase 6 may add a "re-grade old plans" sweeper.
- **Plan editing UI.** Plans are read-only artifacts in this phase.
- **Streaming LLM responses.** Tool use returns the structured output at the end of the call. No streaming.
- **Multi-turn conversation with the LLM.** Single-shot. If the first call fails validation, the file fails; we don't ask the LLM to "try again."
- **MCP tools for downstream consumers.** Phase 4.

## Risks & mitigations

| Risk                                                                      | Mitigation                                                                       |
|---------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| LLM hallucinates a plan that *validates structurally* but produces wrong data | The eval suite is exactly this catch. Hard CI gate at 0.90 score.            |
| Anthropic API outage blocks ingestion                                     | `TransientCleaningError` → Arq retries with backoff; file stays in `processing`  |
| Cost runaway in dev                                                       | Mock LLM in CI; nightly real-API run is budget-capped via `ANTHROPIC_MAX_TOKENS_PER_RUN` |
| Plan grammar evolution breaks old cache entries                           | `_PLAN_VERSION` in fingerprint key — auto-invalidates                            |
| LLM emits a plan referencing a column with a *typo* of a real column      | `_validate_plan_against_df` rejects it before apply                              |
| Sample size (head 20) doesn't expose a problematic column further down    | Phase 2's `apply` is strict-false on coercion — bad rows become null, file still completes; eval suite scoring catches systemic issues |

## Acceptance summary (the four sentences for the LinkedIn post)

> *"I added LLM-driven schema understanding to signal-ingest. A new source's schema gets fingerprinted; the first file calls Claude Sonnet via Anthropic's tool-use API to emit a structured `CleaningPlan` — same Pydantic shape the hand-coded plans used in Phase 2. The plan is cached in Postgres by `(source, fingerprint, plan_version)`, so a million identical-schema files cost one LLM call total. CI runs an eval suite against real golden datasets nightly and hard-gates the score; plans that don't produce the expected canonical output don't make it past main."*

That is what Phase 3 is. The plumbing was Phase 2's job; this is the AI part.
