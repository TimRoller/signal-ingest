from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from shared.cleaning.operations import Operation


class CleaningPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    source: str
    operations: list[Operation]
