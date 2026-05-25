from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.ingest_api.config import Settings
from services.ingest_api.queue import ArqEnqueuer, JobEnqueuer
from services.ingest_api.storage import S3Config, S3Storage


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] | None = getattr(
        request.app.state, "session_factory", None
    )
    if factory is None:
        raise RuntimeError("session_factory not initialized on app state")
    return factory


async def get_session(
    factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


def get_storage(request: Request) -> S3Storage:
    storage: S3Storage | None = getattr(request.app.state, "storage", None)
    if storage is None:
        raise RuntimeError("storage not initialized on app state")
    return storage


def get_enqueuer(request: Request) -> JobEnqueuer:
    enqueuer: JobEnqueuer | None = getattr(request.app.state, "enqueuer", None)
    if enqueuer is None:
        raise RuntimeError("enqueuer not initialized on app state")
    return enqueuer


__all__ = ["ArqEnqueuer", "JobEnqueuer", "get_enqueuer"]


def build_storage(settings: Settings) -> S3Storage:
    return S3Storage(
        S3Config(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
            bucket=settings.bronze_bucket,
        )
    )
