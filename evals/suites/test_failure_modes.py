from __future__ import annotations

import asyncio

import polars as pl
import pytest

from evals.suites.conftest import FailureDataset, discover_failures
from shared.cleaning import PermanentCleaningError, apply
from shared.llm import validate_plan_against_df
from shared.llm.generator import AnthropicPlanGenerator, PlanGenerationError


@pytest.fixture(scope="module")
def generator() -> AnthropicPlanGenerator:
    return AnthropicPlanGenerator()


@pytest.mark.parametrize("dataset", list(discover_failures()), ids=lambda d: d.name)
def test_failure_mode_dataset_does_not_silently_succeed(
    dataset: FailureDataset, generator: AnthropicPlanGenerator
) -> None:
    """A failure-mode dataset must NOT produce a successful cleaned output.

    Either CSV parsing fails (caller's job), or the LLM call/validation fails,
    or applying the plan raises. Any of these is an acceptable outcome.
    """
    try:
        df = pl.read_csv(dataset.csv_path)
    except Exception:
        return  # CSV parsing rejected the file — that's a correct failure

    try:
        generated = asyncio.run(generator.generate(dataset.name, df))
    except PlanGenerationError:
        return

    try:
        validate_plan_against_df(generated.plan, df)
        apply(generated.plan, df)
    except PermanentCleaningError:
        return

    pytest.fail(f"{dataset.name} produced a 'successful' cleaning when it should have failed")
