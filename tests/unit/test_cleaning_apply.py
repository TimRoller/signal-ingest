from __future__ import annotations

import polars as pl
import pytest

from shared.cleaning import PermanentCleaningError, apply
from shared.cleaning.operations import (
    CoerceType,
    DropNulls,
    FillNull,
    Lowercase,
    ParseDate,
    RenameColumn,
    Trim,
)
from shared.cleaning.plan import CleaningPlan


def _plan(*ops: object) -> CleaningPlan:
    return CleaningPlan(version="test", source="test", operations=list(ops))  # type: ignore[arg-type]


def test_rename_column() -> None:
    df = pl.DataFrame({"a": [1, 2]})
    plan = _plan(RenameColumn.model_validate({"kind": "rename", "from": "a", "to": "b"}))
    out = apply(plan, df)
    assert out.columns == ["b"]


def test_coerce_type_int_drops_invalid_to_null() -> None:
    df = pl.DataFrame({"x": ["10", "junk", "3"]})
    plan = _plan(CoerceType(kind="coerce_type", column="x", to="int"))
    out = apply(plan, df)
    assert out["x"].to_list() == [10, None, 3]
    assert out["x"].dtype == pl.Int64


def test_coerce_type_string() -> None:
    df = pl.DataFrame({"x": [1, 2, 3]})
    plan = _plan(CoerceType(kind="coerce_type", column="x", to="string"))
    out = apply(plan, df)
    assert out["x"].dtype == pl.String
    assert out["x"].to_list() == ["1", "2", "3"]


def test_parse_date_iso_datetime() -> None:
    df = pl.DataFrame({"d": ["2026-01-15 12:00:00", "2026-05-24 09:30:00"]})
    plan = _plan(ParseDate(kind="parse_date", column="d", format="%Y-%m-%d %H:%M:%S"))
    out = apply(plan, df)
    assert out["d"].dtype == pl.Datetime


def test_drop_nulls_filters_rows() -> None:
    df = pl.DataFrame({"id": [1, None, 3], "name": ["a", "b", "c"]})
    plan = _plan(DropNulls(kind="drop_nulls", columns=["id"]))
    out = apply(plan, df)
    assert out.height == 2
    assert out["id"].to_list() == [1, 3]


def test_fill_null_scalar_int() -> None:
    df = pl.DataFrame({"impressions": [10, None, 30]})
    plan = _plan(FillNull(kind="fill_null", column="impressions", value=0))
    out = apply(plan, df)
    assert out["impressions"].to_list() == [10, 0, 30]


def test_trim_strips_whitespace() -> None:
    df = pl.DataFrame({"name": ["  alpha  ", "beta ", " gamma"]})
    plan = _plan(Trim(kind="trim", column="name"))
    out = apply(plan, df)
    assert out["name"].to_list() == ["alpha", "beta", "gamma"]


def test_lowercase() -> None:
    df = pl.DataFrame({"vertical": ["Auto", "RETAIL", "Travel"]})
    plan = _plan(Lowercase(kind="lowercase", column="vertical"))
    out = apply(plan, df)
    assert out["vertical"].to_list() == ["auto", "retail", "travel"]


def test_missing_column_raises_permanent() -> None:
    df = pl.DataFrame({"a": [1]})
    plan = _plan(Trim(kind="trim", column="not_there"))
    with pytest.raises(PermanentCleaningError) as exc:
        apply(plan, df)
    assert "not_there" in str(exc.value)


def test_full_demo_plan_against_synthetic_frame() -> None:
    from shared.cleaning.registry import get_plan

    plan = get_plan("demo")
    assert plan is not None
    df = pl.DataFrame(
        {
            "id": [1, 2, None],
            "name": ["  alpha  ", "beta", "gamma"],
            "value": ["10", "junk", "30"],
        }
    )
    out = apply(plan, df)
    assert out.height == 2  # the None id row dropped
    assert out["name"].to_list() == ["alpha", "beta"]
    assert out["value"].to_list() == [10, None]


def test_full_vendor_a_plan() -> None:
    from shared.cleaning.registry import get_plan

    plan = get_plan("vendor_a")
    assert plan is not None
    df = pl.DataFrame(
        {
            "TS": ["2026-01-15 12:00:00", "2026-05-24 09:30:00"],
            "vertical": ["Auto", "RETAIL"],
            "impressions": [None, 500],
        }
    )
    out = apply(plan, df)
    assert "timestamp" in out.columns
    assert "TS" not in out.columns
    assert out["vertical"].to_list() == ["auto", "retail"]
    assert out["impressions"].to_list() == [0, 500]
