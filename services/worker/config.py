from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://signal:signal@postgres:5432/signal",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379", alias="REDIS_URL")

    s3_endpoint_url: str = Field(default="http://minio:9000", alias="S3_ENDPOINT_URL")
    s3_access_key: str = Field(default="minio", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minio12345", alias="S3_SECRET_KEY")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    bronze_bucket: str = Field(default="bronze", alias="BRONZE_BUCKET")
    silver_bucket: str = Field(default="silver", alias="SILVER_BUCKET")

    otlp_endpoint: str | None = Field(default=None, alias="OTLP_ENDPOINT")
    service_name: str = Field(default="worker", alias="SERVICE_NAME")

    max_tries: int = Field(default=5, alias="WORKER_MAX_TRIES")
    metrics_port: int = Field(default=9100, alias="WORKER_METRICS_PORT")
