"""Expected canonical output for signups_v1.csv."""

from __future__ import annotations

import polars as pl

SOURCE = "signups_v1"


def expected() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "customer_id": [1, 2, 3, 4],
            "signup_source": ["web", "mobile", "email", "web"],
            "signups": [3, 0, 7, 2],
        }
    )
