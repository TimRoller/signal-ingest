from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from shared.db.base import Base


class FileStatus(StrEnum):
    received = "received"
    processing = "processing"
    cleaned = "cleaned"
    failed = "failed"


file_status_enum = PgEnum(
    FileStatus,
    name="file_status",
    create_type=False,
    values_callable=lambda enum: [member.value for member in enum],
)


class FileORM(Base):
    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("source", "sha256", name="files_source_sha256_key"),
        CheckConstraint("byte_size >= 0", name="files_byte_size_nonneg"),
        Index("files_created_at_desc_idx", text("created_at DESC")),
        Index("files_status_idx", "status"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    s3_uri: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[FileStatus] = mapped_column(
        file_status_enum, nullable=False, default=FileStatus.received
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


SOURCE_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


class FileRecord(BaseModel):
    id: UUID
    source: str
    original_name: str
    sha256: str
    byte_size: int
    s3_uri: str
    status: FileStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class UploadResponse(BaseModel):
    file: FileRecord
    duplicate: bool = Field(
        description="True when the upload matched an existing (source, sha256) row"
    )


class FileListResponse(BaseModel):
    items: list[FileRecord]
    total: int
    limit: int
    offset: int
