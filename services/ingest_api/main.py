from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingest_api.config import Settings
from services.ingest_api.dependencies import (
    build_storage,
    get_session,
    get_settings,
    get_storage,
)
from services.ingest_api.metrics import UPLOAD_BYTES, UPLOADS_TOTAL
from services.ingest_api.storage import S3Storage
from services.ingest_api.uploads import (
    buffer_and_hash,
    build_s3_key,
    read_all,
    validate_content_type,
    validate_source,
)
from shared.db.repositories.files import FilesRepository
from shared.db.session import make_engine, make_session_factory
from shared.models.file import FileListResponse, FileRecord, UploadResponse
from shared.observability.init import init_tracing, instrument_fastapi

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_tracing(settings.service_name, settings.otlp_endpoint)

    engine = make_engine(settings.database_url)
    app.state.session_factory = make_session_factory(engine)

    storage = build_storage(settings)
    await storage.ensure_bucket()
    app.state.storage = storage

    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="signal-ingest / ingest_api", version="0.2.0", lifespan=lifespan)
instrument_fastapi(app)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_csv(
    file: Annotated[UploadFile, File(...)],
    source: Annotated[str, Form(...)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[S3Storage, Depends(get_storage)],
) -> UploadResponse:
    validated_source = validate_source(source)
    validate_content_type(file.content_type, settings.allowed_content_types)

    buffered = await buffer_and_hash(file, settings.max_upload_bytes)
    key = build_s3_key(source=validated_source, sha256=buffered.sha256)
    s3_uri = storage.uri_for(key)

    repo = FilesRepository(session)
    row, created = await repo.insert_if_absent(
        source=validated_source,
        original_name=buffered.original_name,
        sha256=buffered.sha256,
        byte_size=buffered.byte_size,
        s3_uri=s3_uri,
    )
    await session.flush()

    if created:
        try:
            await storage.put_object(
                key=key,
                body=read_all(buffered.spooled),
                metadata={
                    "original-name": buffered.original_name,
                    "source": validated_source,
                },
            )
        except Exception as exc:
            await repo.delete_by_id(row.id)
            await session.commit()
            UPLOADS_TOTAL.labels(source=validated_source, result="error").inc()
            _logger.exception("MinIO upload failed; row %s rolled back", row.id)
            raise HTTPException(status_code=500, detail="storage write failed") from exc

    buffered.spooled.close()
    await session.commit()

    if created:
        UPLOADS_TOTAL.labels(source=validated_source, result="created").inc()
        UPLOAD_BYTES.labels(source=validated_source).observe(buffered.byte_size)
        return UploadResponse(file=FileRecord.model_validate(row), duplicate=False)

    UPLOADS_TOTAL.labels(source=validated_source, result="duplicate").inc()
    response = UploadResponse(file=FileRecord.model_validate(row), duplicate=True)
    return response


@app.get("/status/{file_id}", response_model=FileRecord)
async def get_status(
    file_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileRecord:
    repo = FilesRepository(session)
    row = await repo.get(file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="file not found")
    return FileRecord.model_validate(row)


@app.get("/files", response_model=FileListResponse)
async def list_files(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 20,
    offset: int = 0,
    source: str | None = None,
) -> FileListResponse:
    if not (1 <= limit <= 100) or offset < 0:
        raise HTTPException(status_code=422, detail="limit ∈ [1,100], offset >= 0")

    repo = FilesRepository(session)
    items, total = await repo.list(limit=limit, offset=offset, source=source)
    return FileListResponse(
        items=[FileRecord.model_validate(row) for row in items],
        total=total,
        limit=limit,
        offset=offset,
    )
