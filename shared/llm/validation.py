from __future__ import annotations

import polars as pl

from shared.cleaning import PermanentCleaningError
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


def validate_plan_against_df(plan: CleaningPlan, df: pl.DataFrame) -> None:
    """Run cheap structural checks before the applier touches data.

    Catches plausibly-valid LLM output that would crash or corrupt:
    - operations referencing columns not present in the source frame
    - renames whose target collides with an existing column
    """
    columns_in_play = set(df.columns)

    for op in plan.operations:
        match op:
            case RenameColumn(from_=src, to=dst):
                _must_exist(src, columns_in_play, op)
                if dst in columns_in_play and dst != src:
                    raise PermanentCleaningError(
                        f"rename target {dst!r} collides with existing column"
                    )
                columns_in_play.discard(src)
                columns_in_play.add(dst)
            case CoerceType(column=col):
                _must_exist(col, columns_in_play, op)
            case ParseDate(column=col):
                _must_exist(col, columns_in_play, op)
            case DropNulls(columns=cols):
                for c in cols:
                    _must_exist(c, columns_in_play, op)
            case FillNull(column=col):
                _must_exist(col, columns_in_play, op)
            case Trim(column=col):
                _must_exist(col, columns_in_play, op)
            case Lowercase(column=col):
                _must_exist(col, columns_in_play, op)


def _must_exist(column: str, present: set[str], op: object) -> None:
    if column not in present:
        raise PermanentCleaningError(
            f"plan references unknown column {column!r} for op {type(op).__name__}; "
            f"available: {sorted(present)}"
        )
