from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from shared.db.base import Base


class CleaningPlanORM(Base):
    __tablename__ = "cleaning_plans"
    __table_args__ = (
        UniqueConstraint(
            "source", "fingerprint", "plan_version", name="cleaning_plans_source_fp_version_key"
        ),
        Index("cleaning_plans_source_idx", "source"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_version: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CleaningPlanRecord(BaseModel):
    id: UUID
    source: str
    fingerprint: str
    plan_version: str
    plan_json: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
