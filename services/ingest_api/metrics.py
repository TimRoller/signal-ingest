from __future__ import annotations

from prometheus_client import Counter, Histogram

UPLOADS_TOTAL = Counter(
    "signal_uploads_total",
    "CSV uploads by source and outcome",
    labelnames=("source", "result"),
)

UPLOAD_BYTES = Histogram(
    "signal_upload_bytes",
    "Byte size of uploaded CSVs",
    labelnames=("source",),
    buckets=(1024, 10_240, 102_400, 1_048_576, 10_485_760, 104_857_600),
)
