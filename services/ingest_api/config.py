from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://signal:signal@postgres:5432/signal",
        alias="DATABASE_URL",
    )
    s3_endpoint_url: str = Field(default="http://minio:9000", alias="S3_ENDPOINT_URL")
    s3_access_key: str = Field(default="minio", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minio12345", alias="S3_SECRET_KEY")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    bronze_bucket: str = Field(default="bronze", alias="BRONZE_BUCKET")

    max_upload_bytes: int = Field(default=100 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    allowed_content_types: tuple[str, ...] = (
        "text/csv",
        "application/csv",
        "application/octet-stream",
    )

    otlp_endpoint: str | None = Field(default=None, alias="OTLP_ENDPOINT")
    service_name: str = Field(default="ingest_api", alias="SERVICE_NAME")
