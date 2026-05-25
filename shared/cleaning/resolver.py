from __future__ import annotations

import logging

import polars as pl
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.cleaning.plan import CleaningPlan
from shared.cleaning.registry import get_plan as get_hardcoded_plan
from shared.db.repositories.cleaning_plans import CleaningPlansRepository
from shared.db.session import session_scope
from shared.llm import (
    PLAN_VERSION,
    GeneratedPlan,
    PlanGenerationError,
    PlanGenerator,
    fingerprint,
    validate_plan_against_df,
)

_logger = logging.getLogger(__name__)


class ResolvedPlan:
    __slots__ = ("plan", "cache_hit", "generated")

    def __init__(
        self,
        plan: CleaningPlan,
        cache_hit: bool,
        generated: GeneratedPlan | None,
    ) -> None:
        self.plan = plan
        self.cache_hit = cache_hit
        self.generated = generated


async def resolve_plan(
    *,
    source: str,
    df: pl.DataFrame,
    session_factory: async_sessionmaker[AsyncSession],
    llm: PlanGenerator | None,
) -> ResolvedPlan:
    """Cache-first plan resolution. Falls back to hard-coded registry, then LLM."""
    fp = fingerprint(
        source=source,
        columns=df.columns,
        dtypes=[str(d) for d in df.dtypes],
    )

    async with session_scope(session_factory) as session:
        cache = CleaningPlansRepository(session)
        cached = await cache.get(source=source, fingerprint=fp, plan_version=PLAN_VERSION)
        if cached is not None:
            plan = CleaningPlan.model_validate(cached.plan_json)
            validate_plan_against_df(plan, df)
            return ResolvedPlan(plan=plan, cache_hit=True, generated=None)

    hardcoded = get_hardcoded_plan(source)
    if hardcoded is not None:
        validate_plan_against_df(hardcoded, df)
        return ResolvedPlan(plan=hardcoded, cache_hit=False, generated=None)

    if llm is None:
        raise PlanGenerationError(
            f"no cached plan, no hard-coded plan, and no LLM available for source={source!r}"
        )

    sample = df.head(20)
    generated = await llm.generate(source, sample)
    validate_plan_against_df(generated.plan, df)

    async with session_scope(session_factory) as session:
        cache = CleaningPlansRepository(session)
        existing = await cache.get(source=source, fingerprint=fp, plan_version=PLAN_VERSION)
        if existing is None:
            await cache.put(
                source=source,
                fingerprint=fp,
                plan_version=PLAN_VERSION,
                plan_json=generated.plan.model_dump(by_alias=True),
                model=generated.model,
                input_tokens=generated.input_tokens,
                output_tokens=generated.output_tokens,
                cost_usd=generated.cost_usd,  # type: ignore[arg-type]
            )

    return ResolvedPlan(plan=generated.plan, cache_hit=False, generated=generated)
