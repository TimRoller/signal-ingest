"""processing_jobs table

Revision ID: 0002_processing_jobs
Revises: 0001_initial_files
Create Date: 2026-05-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_processing_jobs"
down_revision: str | None = "0001_initial_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    job_status = postgresql.ENUM(
        "queued",
        "running",
        "cleaned",
        "failed",
        name="job_status",
        create_type=True,
    )
    job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "processing_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued",
                "running",
                "cleaned",
                "failed",
                name="job_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'queued'::job_status"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index("processing_jobs_file_id_idx", "processing_jobs", ["file_id"])
    op.create_index("processing_jobs_status_idx", "processing_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("processing_jobs_status_idx", table_name="processing_jobs")
    op.drop_index("processing_jobs_file_id_idx", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.execute("DROP TYPE IF EXISTS job_status")
