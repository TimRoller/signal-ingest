from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from tempfile import SpooledTemporaryFile

from fastapi import HTTPException, UploadFile, status

from shared.models.file import SOURCE_PATTERN

_SOURCE_RE = re.compile(SOURCE_PATTERN)
_CHUNK_BYTES = 8 * 1024
_SPOOL_MAX_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class BufferedUpload:
    sha256: str
    byte_size: int
    spooled: SpooledTemporaryFile[bytes]
    original_name: str


def validate_source(source: str) -> str:
    if not _SOURCE_RE.match(source):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="source must match ^[a-z][a-z0-9_]{1,63}$",
        )
    return source


def validate_content_type(content_type: str | None, allowed: tuple[str, ...]) -> None:
    if content_type is None or content_type.split(";")[0].strip() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported content-type: {content_type}",
        )


async def buffer_and_hash(upload: UploadFile, max_bytes: int) -> BufferedUpload:
    spooled: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(max_size=_SPOOL_MAX_BYTES)
    digest = hashlib.sha256()
    size = 0

    while True:
        chunk = await upload.read(_CHUNK_BYTES)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            spooled.close()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"detail": "file too large", "limit_bytes": max_bytes},
            )
        digest.update(chunk)
        spooled.write(chunk)

    spooled.seek(0)
    return BufferedUpload(
        sha256=digest.hexdigest(),
        byte_size=size,
        spooled=spooled,
        original_name=upload.filename or "unnamed.csv",
    )


def build_s3_key(*, source: str, sha256: str, uploaded_at: datetime | None = None) -> str:
    moment = uploaded_at or datetime.now(UTC)
    return f"{source}/{moment.year:04d}/{moment.month:02d}/{moment.day:02d}/{sha256}.csv"


def read_all(spooled: SpooledTemporaryFile[bytes]) -> bytes:
    spooled.seek(0)
    return spooled.read()
