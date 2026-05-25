from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import aiobotocore.session
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class S3Config:
    endpoint_url: str
    access_key: str
    secret_key: str
    region: str
    bucket: str


class S3Storage:
    def __init__(self, config: S3Config) -> None:
        self._config = config
        self._session = aiobotocore.session.get_session()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[object]:
        async with self._session.create_client(
            "s3",
            endpoint_url=self._config.endpoint_url,
            aws_access_key_id=self._config.access_key,
            aws_secret_access_key=self._config.secret_key,
            region_name=self._config.region,
        ) as client:
            yield client

    async def ensure_bucket(self) -> None:
        async with self._client() as client:
            try:
                await client.head_bucket(Bucket=self._config.bucket)  # type: ignore[attr-defined]
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchBucket", "NotFound"}:
                    await client.create_bucket(Bucket=self._config.bucket)  # type: ignore[attr-defined]
                else:
                    raise

    async def put_object(self, *, key: str, body: bytes, metadata: dict[str, str]) -> None:
        async with self._client() as client:
            await client.put_object(  # type: ignore[attr-defined]
                Bucket=self._config.bucket,
                Key=key,
                Body=body,
                Metadata=metadata,
            )

    async def get_object(self, key: str) -> bytes:
        async with self._client() as client:
            response = await client.get_object(Bucket=self._config.bucket, Key=key)  # type: ignore[attr-defined]
            async with response["Body"] as stream:
                data: bytes = await stream.read()
                return data

    async def delete_object(self, key: str) -> None:
        async with self._client() as client:
            await client.delete_object(Bucket=self._config.bucket, Key=key)  # type: ignore[attr-defined]

    def uri_for(self, key: str) -> str:
        return f"s3://{self._config.bucket}/{key}"

    @property
    def bucket(self) -> str:
        return self._config.bucket

    @staticmethod
    def parse_uri(uri: str) -> tuple[str, str]:
        if not uri.startswith("s3://"):
            raise ValueError(f"not an s3 uri: {uri}")
        bucket, _, key = uri[len("s3://") :].partition("/")
        if not bucket or not key:
            raise ValueError(f"malformed s3 uri: {uri}")
        return bucket, key
