from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs
from testcontainers.postgres import PostgresContainer

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    container = PostgresContainer(image="pgvector/pgvector:pg16", driver="asyncpg")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def minio_container() -> Iterator[DockerContainer]:
    container = (
        DockerContainer("minio/minio:latest")
        .with_env("MINIO_ROOT_USER", "minio")
        .with_env("MINIO_ROOT_PASSWORD", "minio12345")
        .with_exposed_ports(9000)
        .with_command("server /data")
    )
    container.start()
    wait_for_logs(container, "API:")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session")
def s3_endpoint_url(minio_container: DockerContainer) -> str:
    host = minio_container.get_container_host_ip()
    port = minio_container.get_exposed_port(9000)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session", autouse=True)
def run_migrations(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade failed (exit {result.returncode})\n"
            f"DATABASE_URL={database_url}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    s3_endpoint_url: str,
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("S3_ENDPOINT_URL", s3_endpoint_url)
    monkeypatch.setenv("S3_ACCESS_KEY", "minio")
    monkeypatch.setenv("S3_SECRET_KEY", "minio12345")
    monkeypatch.setenv("S3_REGION", "us-east-1")
    monkeypatch.setenv("BRONZE_BUCKET", "bronze")

    from services.ingest_api.dependencies import get_settings
    from services.ingest_api.main import app

    get_settings.cache_clear()

    async with (
        LifespanManager(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac,
    ):
        yield ac

    get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def truncate_files_between_tests(database_url: str) -> AsyncIterator[None]:
    yield
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text("TRUNCATE TABLE files"))
    await engine.dispose()
