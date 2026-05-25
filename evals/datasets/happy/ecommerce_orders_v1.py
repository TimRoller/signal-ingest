"""Expected canonical output for ecommerce_orders_v1.csv."""

from __future__ import annotations

import polars as pl

SOURCE = "ecommerce_orders_v1"


def expected() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "order_id": [1001, 1002, 1003],
            "customer_name": ["alice smith", "bob jones", "carol mendez"],
            "amount_usd": [49.99, 19.50, 124.00],
        }
    )
