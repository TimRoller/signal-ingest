from __future__ import annotations

import io
import logging
import time
from typing import Any
from uuid import UUID

import polars as pl

from services.ingest_api.storage import S3Storage
from services.worker.metrics import (
    CLEANED_TOTAL,
    CLEANING_DURATION,
    LLM_CALLS_TOTAL,
    LLM_COST_USD,
    PLAN_CACHE_HITS,
    PLAN_CACHE_MISSES,
    ROWS_PROCESSED,
)
from shared.cleaning import (
    PermanentCleaningError,
    TransientCleaningError,
    apply,
    resolve_plan,
)
from shared.db.repositories.files import FilesRepository
from shared.db.repositories.processing_jobs import ProcessingJobsRepository
from shared.db.session import session_scope
from shared.llm import PlanGenerationError
from shared.models.file import FileStatus

_logger = logging.getLogger(__name__)


async def clean_file(ctx: dict[str, Any], file_id: str) -> None:
    fid = UUID(file_id)
    session_factory = ctx["session_factory"]
    bronze_storage: S3Storage = ctx["bronze_storage"]
    silver_storage: S3Storage = ctx["silver_storage"]
    llm = ctx.get("plan_generator")

    started = time.monotonic()

    async with session_scope(session_factory) as session:
        files = FilesRepository(session)
        jobs = ProcessingJobsRepository(session)

        row = await files.get(fid)
        if row is None:
            raise PermanentCleaningError(f"file {fid} not found")

        await jobs.mark_running(fid)
        await files.set_status(fid, FileStatus.processing)

    source = row.source

    try:
        bronze_bytes = await _download_bronze(bronze_storage, row.s3_uri)
        df = _read_csv(bronze_bytes)

        try:
            resolved = await resolve_plan(
                source=source,
                df=df,
                session_factory=session_factory,
                llm=llm,
            )
        except PlanGenerationError as exc:
            LLM_CALLS_TOTAL.labels(source=source, model="unknown", result="generation_failed").inc()
            raise PermanentCleaningError(str(exc)) from exc

        if resolved.cache_hit:
            PLAN_CACHE_HITS.labels(source=source).inc()
        else:
            PLAN_CACHE_MISSES.labels(source=source).inc()
            if resolved.generated is not None:
                LLM_CALLS_TOTAL.labels(
                    source=source, model=resolved.generated.model, result="ok"
                ).inc()
                LLM_COST_USD.labels(source=source, model=resolved.generated.model).inc(
                    float(resolved.generated.cost_usd)  # type: ignore[arg-type]
                )

        cleaned = apply(resolved.plan, df)
        silver_key = _silver_key(source, fid, row.created_at)
        parquet_bytes = _to_parquet(cleaned)
        await silver_storage.put_object(
            key=silver_key,
            body=parquet_bytes,
            metadata={
                "source": source,
                "file-id": str(fid),
                "plan-version": resolved.plan.version,
            },
        )
    except PermanentCleaningError as exc:
        await _mark_failed(session_factory, fid, source, str(exc))
        return
    except TransientCleaningError:
        CLEANED_TOTAL.labels(source=source, result="failed_transient").inc()
        raise
    except Exception as exc:
        _logger.exception("transient failure cleaning file %s", fid)
        CLEANED_TOTAL.labels(source=source, result="failed_transient").inc()
        raise TransientCleaningError(str(exc)) from exc

    async with session_scope(session_factory) as session:
        files = FilesRepository(session)
        jobs = ProcessingJobsRepository(session)
        await files.set_status(fid, FileStatus.cleaned)
        await jobs.mark_cleaned(fid)

    CLEANED_TOTAL.labels(source=source, result="cleaned").inc()
    ROWS_PROCESSED.labels(source=source).observe(cleaned.height)
    CLEANING_DURATION.labels(source=source).observe(time.monotonic() - started)


async def _mark_failed(session_factory: Any, fid: UUID, source: str, error: str) -> None:
    async with session_scope(session_factory) as session:
        files = FilesRepository(session)
        jobs = ProcessingJobsRepository(session)
        await files.set_status(fid, FileStatus.failed, error_message=error)
        await jobs.mark_failed(fid, error)
    CLEANED_TOTAL.labels(source=source, result="failed_permanent").inc()


async def _download_bronze(storage: S3Storage, s3_uri: str) -> bytes:
    _, key = S3Storage.parse_uri(s3_uri)
    return await storage.get_object(key)


def _read_csv(data: bytes) -> pl.DataFrame:
    try:
        return pl.read_csv(io.BytesIO(data))
    except Exception as exc:
        raise PermanentCleaningError(f"failed to parse CSV: {exc}") from exc


def _to_parquet(df: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return buffer.getvalue()


def _silver_key(source: str, file_id: UUID, created_at: Any) -> str:
    moment = created_at
    return f"{source}/{moment.year:04d}/{moment.month:02d}/{moment.day:02d}/{file_id}.parquet"
