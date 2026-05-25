from __future__ import annotations

import asyncio
from pathlib import Path

import polars as pl
import pytest

from evals.suites.conftest import HappyDataset, discover_happy
from shared.cleaning import apply
from shared.llm import validate_plan_against_df
from shared.llm.generator import AnthropicPlanGenerator

PASS_THRESHOLD = 0.90


def _grade(actual: pl.DataFrame, expected: pl.DataFrame) -> tuple[float, dict[str, float]]:
    """Returns overall score in [0, 1] and per-axis scores."""
    expected_cols = set(expected.columns)
    actual_cols = set(actual.columns)
    column_match = len(expected_cols & actual_cols) / max(len(expected_cols), 1)

    common_cols = list(expected_cols & actual_cols)
    if not common_cols:
        return 0.0, {"columns": column_match, "dtypes": 0.0, "cells": 0.0}

    expected_dtypes = {c: str(expected.schema[c]) for c in common_cols}
    actual_dtypes = {c: str(actual.schema[c]) for c in common_cols}
    dtype_match = sum(
        1 for c in common_cols if _dtype_compatible(expected_dtypes[c], actual_dtypes[c])
    ) / max(len(common_cols), 1)

    schema_score = 0.5 * column_match + 0.5 * dtype_match

    if expected.height == 0 or actual.height == 0:
        cell_score = 1.0 if expected.height == actual.height else 0.0
    else:
        n_compare = min(expected.height, actual.height)
        e = expected.select(common_cols).head(n_compare)
        a = actual.select(common_cols).head(n_compare)
        total_cells = n_compare * len(common_cols)
        eq_cells = sum(
            int(e[c][i] == a[c][i] or (e[c][i] is None and a[c][i] is None))
            for c in common_cols
            for i in range(n_compare)
        )
        cell_score = eq_cells / max(total_cells, 1)

    overall = 0.5 * schema_score + 0.5 * cell_score
    return overall, {"columns": column_match, "dtypes": dtype_match, "cells": cell_score}


def _dtype_compatible(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    numeric = {"Int64", "Int32", "Float64", "Float32"}
    return expected in numeric and actual in numeric


@pytest.fixture(scope="module")
def generator() -> AnthropicPlanGenerator:
    return AnthropicPlanGenerator()


@pytest.mark.parametrize("dataset", list(discover_happy()), ids=lambda d: d.name)
def test_happy_dataset_grades_above_threshold(
    dataset: HappyDataset, generator: AnthropicPlanGenerator, tmp_path: Path
) -> None:
    df = pl.read_csv(dataset.csv_path)
    generated = asyncio.run(generator.generate(dataset.name, df))

    validate_plan_against_df(generated.plan, df)
    cleaned = apply(generated.plan, df)

    score, axes = _grade(cleaned, dataset.expected)

    report = tmp_path / f"{dataset.name}.json"
    report.write_text(
        f'{{"score": {score}, "axes": {axes}, "model": "{generated.model}", '
        f'"input_tokens": {generated.input_tokens}, "output_tokens": {generated.output_tokens}}}'
    )
    print(f"\n{dataset.name}: score={score:.3f} axes={axes}")

    assert score >= PASS_THRESHOLD, (
        f"{dataset.name} scored {score:.3f} < {PASS_THRESHOLD}; axes={axes}"
    )
