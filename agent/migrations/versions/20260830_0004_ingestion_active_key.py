"""Guarantee one active ingestion job per paper.

Revision ID: 20260830_0004
Revises: 20260829_0003
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0004"
down_revision: str | None = "20260829_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs",
        sa.Column("active_key", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE ingestion_jobs SET active_key = paper_id WHERE status IN ('QUEUED', 'RUNNING')"
    )
    op.create_unique_constraint(
        "uq_ingestion_jobs_active_key",
        "ingestion_jobs",
        ["active_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ingestion_jobs_active_key",
        "ingestion_jobs",
        type_="unique",
    )
    op.drop_column("ingestion_jobs", "active_key")
