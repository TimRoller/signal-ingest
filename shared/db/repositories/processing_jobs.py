from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.processing_job import JobStatus, ProcessingJobORM


class ProcessingJobsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_queued(self, file_id: UUID) -> ProcessingJobORM:
        existing = await self._get_latest_for_file(file_id)
        if existing is not None:
            existing.status = JobStatus.queued
            existing.last_error = None
            existing.started_at = None
            existing.finished_at = None
            await self._session.flush()
            return existing

        job = ProcessingJobORM(file_id=file_id, status=JobStatus.queued, attempts=0)
        self._session.add(job)
        await self._session.flush()
        return job

    async def mark_running(self, file_id: UUID) -> ProcessingJobORM:
        job = await self._require_latest_for_file(file_id)
        job.status = JobStatus.running
        job.attempts = job.attempts + 1
        job.started_at = datetime.now(UTC)
        job.last_error = None
        await self._session.flush()
        return job

    async def mark_cleaned(self, file_id: UUID) -> ProcessingJobORM:
        job = await self._require_latest_for_file(file_id)
        job.status = JobStatus.cleaned
        job.finished_at = datetime.now(UTC)
        job.last_error = None
        await self._session.flush()
        return job

    async def mark_failed(self, file_id: UUID, error: str) -> ProcessingJobORM:
        job = await self._require_latest_for_file(file_id)
        job.status = JobStatus.failed
        job.finished_at = datetime.now(UTC)
        job.last_error = error
        await self._session.flush()
        return job

    async def get_latest_for_file(self, file_id: UUID) -> ProcessingJobORM | None:
        return await self._get_latest_for_file(file_id)

    async def _get_latest_for_file(self, file_id: UUID) -> ProcessingJobORM | None:
        result = await self._session.execute(
            select(ProcessingJobORM)
            .where(ProcessingJobORM.file_id == file_id)
            .order_by(ProcessingJobORM.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _require_latest_for_file(self, file_id: UUID) -> ProcessingJobORM:
        job = await self._get_latest_for_file(file_id)
        if job is None:
            raise RuntimeError(f"no processing_job row for file_id={file_id}")
        return job
