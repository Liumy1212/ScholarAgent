"""Create the persistent paper library file inventory.

Revision ID: 20260829_0002
Revises: 20260825_0001
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0002"
down_revision: str | None = "20260825_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_files",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=2048), nullable=False),
        sa.Column("path_key", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_status", sa.String(length=32), nullable=False),
        sa.Column("paper_id", sa.String(length=64), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "path_key",
            "sha256",
            name="uq_library_files_path_sha256",
        ),
    )
    op.create_index("ix_library_files_paper_id", "library_files", ["paper_id"])
    op.create_index("ix_library_files_sha256", "library_files", ["sha256"])
    op.create_index(
        "ix_library_files_list",
        "library_files",
        ["source_status", "discovered_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_library_files_list", table_name="library_files")
    op.drop_index("ix_library_files_sha256", table_name="library_files")
    op.drop_index("ix_library_files_paper_id", table_name="library_files")
    op.drop_table("library_files")
