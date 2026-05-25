from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

PLAN_VERSION = "2026-05-24"


def fingerprint(
    *,
    source: str,
    columns: Iterable[str],
    dtypes: Iterable[str],
    plan_version: str = PLAN_VERSION,
) -> str:
    """Stable hash over (source, sorted columns, paired dtypes, plan_version).

    Bumping ``plan_version`` invalidates every prior cache entry without a migration.
    """
    paired = sorted(zip(columns, dtypes, strict=True), key=lambda p: p[0])
    payload = json.dumps(
        {
            "source": source,
            "columns": [c for c, _ in paired],
            "dtypes": [d for _, d in paired],
            "plan_version": plan_version,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
