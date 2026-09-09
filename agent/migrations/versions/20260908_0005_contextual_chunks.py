"""Store structural and generated context for retrieval chunks.

Revision ID: 20260908_0005
Revises: 20260830_0004
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0005"
down_revision: str | None = "20260830_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("section_path", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("context_text", sa.Text(), nullable=True))
    op.execute("UPDATE chunks SET section_path = '', context_text = ''")
    op.alter_column("chunks", "section_path", existing_type=sa.Text(), nullable=False)
    op.alter_column("chunks", "context_text", existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.drop_column("chunks", "context_text")
    op.drop_column("chunks", "section_path")
