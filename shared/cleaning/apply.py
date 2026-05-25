from __future__ import annotations

import polars as pl

from shared.cleaning.operations import (
    CoerceType,
    DropNulls,
    FillNull,
    Lowercase,
    Operation,
    ParseDate,
    RenameColumn,
    Trim,
)
from shared.cleaning.plan import CleaningPlan


class TransientCleaningError(Exception):
    """Re-raise to let Arq retry with backoff."""


class PermanentCleaningError(Exception):
    """Marks the file as failed; no retry."""


_TYPE_MAP: dict[str, pl.DataType] = {
    "int": pl.Int64(),
    "float": pl.Float64(),
    "bool": pl.Boolean(),
    "string": pl.String(),
    "date": pl.Date(),
    "datetime": pl.Datetime(),
}


def apply(plan: CleaningPlan, df: pl.DataFrame) -> pl.DataFrame:
    for op in plan.operations:
        df = _apply_one(op, df)
    return df


def _apply_one(op: Operation, df: pl.DataFrame) -> pl.DataFrame:
    match op:
        case RenameColumn(from_=src, to=dst):
            _require_column(df, src, op)
            return df.rename({src: dst})

        case CoerceType(column=column, to=to_type):
            _require_column(df, column, op)
            target = _TYPE_MAP[to_type]
            return df.with_columns(pl.col(column).cast(target, strict=False))

        case ParseDate(column=column, format=fmt):
            _require_column(df, column, op)
            return df.with_columns(
                pl.col(column).str.strptime(pl.Datetime, format=fmt, strict=False)
            )

        case DropNulls(columns=columns):
            for c in columns:
                _require_column(df, c, op)
            return df.drop_nulls(subset=columns)

        case FillNull(column=column, value=value):
            _require_column(df, column, op)
            return df.with_columns(pl.col(column).fill_null(value))

        case Trim(column=column):
            _require_column(df, column, op)
            return df.with_columns(pl.col(column).str.strip_chars())

        case Lowercase(column=column):
            _require_column(df, column, op)
            return df.with_columns(pl.col(column).str.to_lowercase())

    raise PermanentCleaningError(f"unknown operation: {op!r}")


def _require_column(df: pl.DataFrame, column: str, op: Operation) -> None:
    if column not in df.columns:
        raise PermanentCleaningError(
            f"column {column!r} missing for op {type(op).__name__}; available: {df.columns}"
        )
