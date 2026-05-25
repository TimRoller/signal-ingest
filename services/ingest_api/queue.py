from __future__ import annotations

from typing import Protocol
from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings


class JobEnqueuer(Protocol):
    async def enqueue_clean(self, file_id: UUID) -> None: ...


class ArqEnqueuer:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_clean(self, file_id: UUID) -> None:
        await self._pool.enqueue_job("clean_file", str(file_id))


async def make_pool(redis_url: str) -> ArqRedis:
    settings = RedisSettings.from_dsn(redis_url)
    return await create_pool(settings)
