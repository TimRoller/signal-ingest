"""initial files table

Revision ID: 0001_initial_files
Revises:
Create Date: 2026-05-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_files"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    file_status = postgresql.ENUM(
        "received",
        "processing",
        "cleaned",
        "failed",
        name="file_status",
        create_type=True,
    )
    file_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("s3_uri", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "received",
                "processing",
                "cleaned",
                "failed",
                name="file_status",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'received'::file_status"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.CheckConstraint("byte_size >= 0", name="files_byte_size_nonneg"),
        sa.UniqueConstraint("source", "sha256", name="files_source_sha256_key"),
    )

    op.create_index(
        "files_created_at_desc_idx",
        "files",
        [sa.text("created_at DESC")],
    )
    op.create_index("files_status_idx", "files", ["status"])


def downgrade() -> None:
    op.drop_index("files_status_idx", table_name="files")
    op.drop_index("files_created_at_desc_idx", table_name="files")
    op.drop_table("files")
    op.execute("DROP TYPE IF EXISTS file_status")
