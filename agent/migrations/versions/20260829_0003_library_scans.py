"""Create leased paper-library scan jobs and item results.

Revision ID: 20260829_0003
Revises: 20260829_0002
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0003"
down_revision: str | None = "20260829_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_scan_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_key", sa.String(length=32), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("registered_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("active_key", name="uq_library_scan_jobs_active_key"),
    )
    op.create_index(
        "ix_library_scan_jobs_claim",
        "library_scan_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_library_scan_jobs_lease",
        "library_scan_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_table(
        "library_scan_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scan_id", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=2048), nullable=False),
        sa.Column("path_key", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("library_file_id", sa.String(length=64), nullable=True),
        sa.Column("paper_id", sa.String(length=64), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["library_scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "path_key", name="uq_library_scan_items_scan_path"),
    )
    op.create_index("ix_library_scan_items_scan_id", "library_scan_items", ["scan_id"])
    op.create_index(
        "ix_library_scan_items_page",
        "library_scan_items",
        ["scan_id", "outcome", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_library_scan_items_page", table_name="library_scan_items")
    op.drop_index("ix_library_scan_items_scan_id", table_name="library_scan_items")
    op.drop_table("library_scan_items")
    op.drop_index("ix_library_scan_jobs_lease", table_name="library_scan_jobs")
    op.drop_index("ix_library_scan_jobs_claim", table_name="library_scan_jobs")
    op.drop_table("library_scan_jobs")
