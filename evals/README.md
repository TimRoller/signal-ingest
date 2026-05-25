# Evals

Eval suite for the LLM-generated `CleaningPlan`s in Phase 3.

## What this tests

For each golden dataset, the suite:

1. Loads the source CSV (`evals/datasets/happy/<name>.csv`)
2. Asks the **real Anthropic API** to generate a `CleaningPlan`
3. Validates the plan structurally against the source columns
4. Applies the plan via the same `shared.cleaning.apply` used in production
5. Compares the cleaned output against the expected canonical output (`<name>.expected.parquet`)
6. Scores on schema match (column names + dtypes, 50% weight) and cell-level equality (50% weight)

For each failure-mode dataset, the suite asserts that the worker pipeline rejects the file with status=`failed` and a permanent error.

## Pass criteria

- **Mean happy-path score ≥ 0.90** across all `happy/` datasets.
- **Every failure-mode dataset** is correctly rejected.

CI fails the run if either condition is unmet.

## Running

### On demand via GitHub Actions

```
gh workflow run evals.yml
```

or trigger from the Actions tab. Requires the `ANTHROPIC_API_KEY` secret in the repo.

### Locally

```
export ANTHROPIC_API_KEY=sk-ant-...
uv run pytest evals/suites -q
```

The local run is the same code as CI; pick one based on whether you want a fresh sandboxed runner or a fast local pass.

## Adding a dataset

1. Drop `evals/datasets/happy/<name>.csv` (your raw, messy input).
2. Drop `evals/datasets/happy/<name>.expected.parquet` (the canonical output you'd expect a clean plan to produce — usually you generate this once by hand-applying a plan and saving the polars output as Parquet).
3. Re-run the suite. If the mean score still ≥ 0.90, you're good.

## Cost discipline

Each dataset = 1 LLM call (the schema is hashed and we honour the same cache as production). A full eval run with 10 happy datasets = ~10 LLM calls. Budget-capped via `ANTHROPIC_MAX_TOKENS_PER_RUN` env (defaults to 50k tokens).
