from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Protocol

import polars as pl

from shared.cleaning.plan import CleaningPlan
from shared.llm.pricing import cost_usd

_logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"


class PlanGenerationError(Exception):
    """Raised when the LLM returns no plan, malformed output, or an API error."""


@dataclass(frozen=True)
class GeneratedPlan:
    plan: CleaningPlan
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> object:
        return cost_usd(
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


class PlanGenerator(Protocol):
    async def generate(self, source: str, sample: pl.DataFrame) -> GeneratedPlan: ...


class MockPlanGenerator:
    """Returns a canned plan for each source. Used by integration tests."""

    def __init__(
        self,
        plans: dict[str, CleaningPlan],
        *,
        model: str = "mock-claude",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self._plans = plans
        self._model = model
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls: list[str] = []

    async def generate(self, source: str, sample: pl.DataFrame) -> GeneratedPlan:
        self.calls.append(source)
        plan = self._plans.get(source)
        if plan is None:
            raise PlanGenerationError(f"mock generator has no plan for source={source!r}")
        return GeneratedPlan(
            plan=plan,
            model=self._model,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )


class AnthropicPlanGenerator:
    """Production generator. Uses tool use to force structured CleaningPlan output."""

    def __init__(self, *, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        from anthropic import AsyncAnthropic

        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise PlanGenerationError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=key)
        self._model = model

    async def generate(self, source: str, sample: pl.DataFrame) -> GeneratedPlan:
        tool_schema = CleaningPlan.model_json_schema()
        prompt = self._build_prompt(source, sample)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                tools=[
                    {
                        "name": "submit_cleaning_plan",
                        "description": (
                            "Emit a CleaningPlan whose deterministic application "
                            "to the sample produces a clean, validated DataFrame."
                        ),
                        "input_schema": tool_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": "submit_cleaning_plan"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise PlanGenerationError(f"anthropic API call failed: {exc}") from exc

        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            raise PlanGenerationError("LLM did not call submit_cleaning_plan")

        try:
            plan = CleaningPlan.model_validate(tool_block.input)
        except Exception as exc:
            raise PlanGenerationError(
                f"LLM tool input failed schema validation: {exc}; raw={tool_block.input!r}"
            ) from exc

        return GeneratedPlan(
            plan=plan,
            model=self._model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def _build_prompt(self, source: str, sample: pl.DataFrame) -> str:
        head = sample.head(20).to_dicts()
        dtypes = {c: str(t) for c, t in zip(sample.columns, sample.dtypes, strict=True)}
        return (
            "You are a data cleaning planner. Inspect the sample rows below and "
            "emit a CleaningPlan via the submit_cleaning_plan tool.\n\n"
            f"source: {source}\n"
            f"columns + dtypes: {json.dumps(dtypes)}\n"
            f"sample rows (up to 20):\n{json.dumps(head, default=str)}\n\n"
            "Guidance:\n"
            "- Use rename to fix obvious column-name issues (e.g. TS → timestamp).\n"
            "- Use coerce_type when values look like a different type than detected.\n"
            "- Use parse_date for string dates; supply strptime format.\n"
            "- Use drop_nulls only when a column is critical (id/foreign key).\n"
            "- Use fill_null with a defensible default; lowercase or trim string cols where helpful.\n"
            "Return one CleaningPlan that is deterministic, safe, and minimal."
        )
