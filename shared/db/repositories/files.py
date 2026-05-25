from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.file import FileORM, FileStatus


class FilesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_if_absent(
        self,
        *,
        source: str,
        original_name: str,
        sha256: str,
        byte_size: int,
        s3_uri: str,
    ) -> tuple[FileORM, bool]:
        """Returns (row, created). created=True if a new row was inserted."""
        stmt = (
            insert(FileORM)
            .values(
                source=source,
                original_name=original_name,
                sha256=sha256,
                byte_size=byte_size,
                s3_uri=s3_uri,
                status=FileStatus.received,
            )
            .on_conflict_do_nothing(constraint="files_source_sha256_key")
            .returning(FileORM)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            return row, True

        existing = await self._session.execute(
            select(FileORM).where(
                FileORM.source == source,
                FileORM.sha256 == sha256,
            )
        )
        return existing.scalar_one(), False

    async def delete_by_id(self, file_id: UUID) -> None:
        row = await self._session.get(FileORM, file_id)
        if row is not None:
            await self._session.delete(row)

    async def get(self, file_id: UUID) -> FileORM | None:
        return await self._session.get(FileORM, file_id)

    async def set_status(
        self, file_id: UUID, status: FileStatus, *, error_message: str | None = None
    ) -> FileORM:
        row = await self._session.get(FileORM, file_id)
        if row is None:
            raise RuntimeError(f"file {file_id} not found")
        row.status = status
        row.error_message = error_message
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        source: str | None = None,
    ) -> tuple[list[FileORM], int]:
        base = select(FileORM)
        count_base = select(func.count()).select_from(FileORM)
        if source is not None:
            base = base.where(FileORM.source == source)
            count_base = count_base.where(FileORM.source == source)

        items_result = await self._session.execute(
            base.order_by(FileORM.created_at.desc()).limit(limit).offset(offset)
        )
        total_result = await self._session.execute(count_base)
        return list(items_result.scalars().all()), int(total_result.scalar_one())
