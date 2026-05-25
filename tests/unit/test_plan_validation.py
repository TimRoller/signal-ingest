from __future__ import annotations

import polars as pl
import pytest

from shared.cleaning import PermanentCleaningError
from shared.cleaning.operations import (
    CoerceType,
    DropNulls,
    Lowercase,
    RenameColumn,
    Trim,
)
from shared.cleaning.plan import CleaningPlan
from shared.llm.validation import validate_plan_against_df


def _plan(*ops: object) -> CleaningPlan:
    return CleaningPlan(version="test", source="test", operations=list(ops))  # type: ignore[arg-type]


def test_validation_passes_for_valid_plan() -> None:
    df = pl.DataFrame({"id": [1], "name": ["a"], "value": [10]})
    plan = _plan(
        Trim(kind="trim", column="name"),
        CoerceType(kind="coerce_type", column="value", to="int"),
    )
    validate_plan_against_df(plan, df)  # no raise


def test_validation_rejects_unknown_column() -> None:
    df = pl.DataFrame({"id": [1]})
    plan = _plan(Lowercase(kind="lowercase", column="not_there"))
    with pytest.raises(PermanentCleaningError) as exc:
        validate_plan_against_df(plan, df)
    assert "not_there" in str(exc.value)


def test_validation_rejects_drop_nulls_with_missing_column() -> None:
    df = pl.DataFrame({"id": [1]})
    plan = _plan(DropNulls(kind="drop_nulls", columns=["id", "ghost"]))
    with pytest.raises(PermanentCleaningError):
        validate_plan_against_df(plan, df)


def test_validation_threads_renames_through_subsequent_ops() -> None:
    df = pl.DataFrame({"TS": ["2026-01-01"], "vertical": ["Auto"]})
    plan = _plan(
        RenameColumn.model_validate({"kind": "rename", "from": "TS", "to": "timestamp"}),
        Lowercase(kind="lowercase", column="vertical"),
    )
    validate_plan_against_df(plan, df)  # no raise — later ops see renamed schema


def test_validation_rejects_rename_target_collision() -> None:
    df = pl.DataFrame({"a": [1], "b": [2]})
    plan = _plan(RenameColumn.model_validate({"kind": "rename", "from": "a", "to": "b"}))
    with pytest.raises(PermanentCleaningError) as exc:
        validate_plan_against_df(plan, df)
    assert "collides" in str(exc.value)
