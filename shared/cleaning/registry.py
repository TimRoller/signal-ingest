from __future__ import annotations

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

_PLAN_VERSION = "2026-05-24"


PLANS: dict[str, CleaningPlan] = {
    "demo": CleaningPlan(
        version=_PLAN_VERSION,
        source="demo",
        operations=[
            Trim(kind="trim", column="name"),
            CoerceType(kind="coerce_type", column="value", to="int"),
            DropNulls(kind="drop_nulls", columns=["id"]),
        ],
    ),
    "vendor_a": CleaningPlan(
        version=_PLAN_VERSION,
        source="vendor_a",
        operations=[
            RenameColumn.model_validate({"kind": "rename", "from": "TS", "to": "timestamp"}),
            ParseDate(kind="parse_date", column="timestamp", format="%Y-%m-%d %H:%M:%S"),
            Lowercase(kind="lowercase", column="vertical"),
            FillNull(kind="fill_null", column="impressions", value=0),
        ],
    ),
}


def get_plan(source: str) -> CleaningPlan | None:
    return PLANS.get(source)
