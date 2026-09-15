"""Add logical knowledge bases and chat scope snapshots.

Revision ID: 20260915_0006
Revises: 20260908_0005
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0006"
down_revision: str | None = "20260908_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("name_key", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_key"),
    )
    op.create_table(
        "knowledge_base_papers",
        sa.Column("knowledge_base_id", sa.String(length=64), nullable=False),
        sa.Column("paper_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("knowledge_base_id", "paper_id"),
    )
    op.create_index("ix_knowledge_base_papers_paper", "knowledge_base_papers", ["paper_id"])
    op.add_column("agent_runs", sa.Column("scope_type", sa.String(length=32), nullable=True))
    op.add_column("agent_runs", sa.Column("scope_key", sa.String(length=255), nullable=True))
    op.add_column("agent_runs", sa.Column("scope_id", sa.String(length=128), nullable=True))
    op.add_column("agent_runs", sa.Column("paper_ids_snapshot", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE agent_runs SET scope_type='LEGACY', "
        "scope_key=CONCAT('LEGACY:', conversation_id), paper_ids_snapshot=JSON_ARRAY()"
    )
    op.alter_column("agent_runs", "scope_type", existing_type=sa.String(length=32), nullable=False)
    op.alter_column("agent_runs", "scope_key", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("agent_runs", "paper_ids_snapshot", existing_type=sa.JSON(), nullable=False)
    op.create_index(
        "ix_agent_runs_history_scope",
        "agent_runs",
        ["conversation_id", "scope_key", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_history_scope", table_name="agent_runs")
    op.drop_column("agent_runs", "paper_ids_snapshot")
    op.drop_column("agent_runs", "scope_id")
    op.drop_column("agent_runs", "scope_key")
    op.drop_column("agent_runs", "scope_type")
    op.drop_index("ix_knowledge_base_papers_paper", table_name="knowledge_base_papers")
    op.drop_table("knowledge_base_papers")
    op.drop_table("knowledge_bases")
