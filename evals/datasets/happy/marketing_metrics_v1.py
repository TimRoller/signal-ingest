"""Expected canonical output for marketing_metrics_v1.csv."""

from __future__ import annotations

import polars as pl

SOURCE = "marketing_metrics_v1"


def expected() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "name": ["alpha", "beta", "gamma", "delta"],
            "value": [10, 20, None, 40],
        }
    )
