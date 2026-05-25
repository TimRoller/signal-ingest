"""cleaning_plans table

Revision ID: 0003_cleaning_plans
Revises: 0002_processing_jobs
Create Date: 2026-05-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_cleaning_plans"
down_revision: str | None = "0002_processing_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cleaning_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("plan_version", sa.Text(), nullable=False),
        sa.Column("plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=10, scale=6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "source",
            "fingerprint",
            "plan_version",
            name="cleaning_plans_source_fp_version_key",
        ),
    )

    op.create_index("cleaning_plans_source_idx", "cleaning_plans", ["source"])


def downgrade() -> None:
    op.drop_index("cleaning_plans_source_idx", table_name="cleaning_plans")
    op.drop_table("cleaning_plans")
