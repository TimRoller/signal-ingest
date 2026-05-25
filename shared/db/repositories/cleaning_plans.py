from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.cleaning_plan_row import CleaningPlanORM


class CleaningPlansRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, *, source: str, fingerprint: str, plan_version: str
    ) -> CleaningPlanORM | None:
        result = await self._session.execute(
            select(CleaningPlanORM).where(
                CleaningPlanORM.source == source,
                CleaningPlanORM.fingerprint == fingerprint,
                CleaningPlanORM.plan_version == plan_version,
            )
        )
        return result.scalar_one_or_none()

    async def put(
        self,
        *,
        source: str,
        fingerprint: str,
        plan_version: str,
        plan_json: dict[str, Any],
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
    ) -> CleaningPlanORM:
        row = CleaningPlanORM(
            source=source,
            fingerprint=fingerprint,
            plan_version=plan_version,
            plan_json=plan_json,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        self._session.add(row)
        await self._session.flush()
        return row
