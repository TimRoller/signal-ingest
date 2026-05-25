from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from shared.cleaning.operations import CoerceType, DropNulls, Trim
from shared.cleaning.plan import CleaningPlan
from shared.llm import PLAN_VERSION
from shared.llm.generator import MockPlanGenerator

NOVEL_SOURCE_CSV = b"customer_id,full_name,signups\n1,  Alice  ,3\n2,Bob,7\n,Carol,2\n"


def _novel_plan() -> CleaningPlan:
    return CleaningPlan(
        version=PLAN_VERSION,
        source="novel_src",
        operations=[
            Trim(kind="trim", column="full_name"),
            CoerceType(kind="coerce_type", column="signups", to="int"),
            DropNulls(kind="drop_nulls", columns=["customer_id"]),
        ],
    )


def _csv(name: str, body: bytes) -> dict:
    return {"file": (name, body, "text/csv")}


async def test_new_source_triggers_llm_then_caches(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[..., Coroutine[Any, Any, None]],
    database_url: str,
) -> None:
    generator = MockPlanGenerator(
        plans={"novel_src": _novel_plan()},
        input_tokens=512,
        output_tokens=64,
    )

    upload = await client.post(
        "/upload", files=_csv("a.csv", NOVEL_SOURCE_CSV), data={"source": "novel_src"}
    )
    assert upload.status_code == 201
    file_id = upload.json()["file"]["id"]

    await run_worker_burst(plan_generator=generator)

    status = await client.get(f"/status/{file_id}")
    assert status.json()["status"] == "cleaned", status.json()
    assert generator.calls == ["novel_src"]

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT source, plan_version, model FROM cleaning_plans"))
        rows = result.all()
    await engine.dispose()
    assert len(rows) == 1
    assert rows[0].source == "novel_src"
    assert rows[0].plan_version == PLAN_VERSION
    assert rows[0].model == "mock-claude"

    # Second upload with same schema → cache hit, no second LLM call.
    second = await client.post(
        "/upload",
        files=_csv("b.csv", NOVEL_SOURCE_CSV + b"3,Dave,8\n"),
        data={"source": "novel_src"},
    )
    second_id = second.json()["file"]["id"]
    await run_worker_burst(plan_generator=generator)

    again = await client.get(f"/status/{second_id}")
    assert again.json()["status"] == "cleaned"
    assert generator.calls == ["novel_src"]  # still just one LLM call


async def test_bad_llm_output_marks_file_failed_permanently(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[..., Coroutine[Any, Any, None]],
    database_url: str,
) -> None:
    # Plan references a column that doesn't exist in the uploaded CSV.
    bad_plan = CleaningPlan(
        version=PLAN_VERSION,
        source="hallucinated",
        operations=[Trim(kind="trim", column="ghost_column")],
    )
    generator = MockPlanGenerator(plans={"hallucinated": bad_plan})

    upload = await client.post(
        "/upload", files=_csv("h.csv", NOVEL_SOURCE_CSV), data={"source": "hallucinated"}
    )
    file_id = upload.json()["file"]["id"]

    await run_worker_burst(plan_generator=generator)

    status = await client.get(f"/status/{file_id}")
    body = status.json()
    assert body["status"] == "failed"
    assert "ghost_column" in (body["error_message"] or "")

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM cleaning_plans"))
        count = result.scalar_one()
    await engine.dispose()
    assert count == 0  # bad plan never cached


async def test_hardcoded_plan_skips_llm(
    client: httpx.AsyncClient,
    run_worker_burst: Callable[..., Coroutine[Any, Any, None]],
) -> None:
    # 'demo' is hard-coded in the registry; LLM should not be consulted.
    generator = MockPlanGenerator(plans={})  # would raise if called

    upload = await client.post(
        "/upload",
        files=_csv("d.csv", b"id,name,value\n1,alpha,10\n"),
        data={"source": "demo"},
    )
    file_id = upload.json()["file"]["id"]

    await run_worker_burst(plan_generator=generator)

    status = await client.get(f"/status/{file_id}")
    assert status.json()["status"] == "cleaned"
    assert generator.calls == []  # never called
