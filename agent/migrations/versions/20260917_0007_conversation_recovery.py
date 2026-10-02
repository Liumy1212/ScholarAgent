"""Persist request IDs for recoverable conversation turns.

Revision ID: 20260917_0007
Revises: 20260915_0006
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_0007"
down_revision: str | None = "20260915_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("request_id", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "request_id")
