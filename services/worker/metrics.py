from __future__ import annotations

from prometheus_client import Counter, Histogram

CLEANED_TOTAL = Counter(
    "signal_cleaned_total",
    "File cleaning attempts by source and result",
    labelnames=("source", "result"),
)

CLEANING_DURATION = Histogram(
    "signal_cleaning_duration_seconds",
    "Wall time of clean_file task",
    labelnames=("source",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

ROWS_PROCESSED = Histogram(
    "signal_rows_processed",
    "Row count of cleaned files",
    labelnames=("source",),
    buckets=(10, 100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000),
)
