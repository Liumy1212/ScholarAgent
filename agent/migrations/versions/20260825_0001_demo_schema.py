"""Create the single-paper Demo schema.

Revision ID: 20260825_0001
Revises: None
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("storage_path", sa.String(length=2048), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("paper_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("failure_retryable", sa.Boolean(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_jobs_paper_id", "ingestion_jobs", ["paper_id"])
    op.create_index(
        "ix_ingestion_jobs_claim",
        "ingestion_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_ingestion_jobs_lease",
        "ingestion_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("vector_id", sa.String(length=36), nullable=False),
        sa.Column("paper_id", sa.String(length=64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("paper_id", "page", "ordinal", name="uq_chunks_paper_page_ordinal"),
        sa.UniqueConstraint("vector_id", name="uq_chunks_vector_id"),
    )
    op.create_index("ix_chunks_paper_id", "chunks", ["paper_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("user_message_id", sa.String(length=128), nullable=False),
        sa.Column("assistant_message_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("answer_mode", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("tool_rounds", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_calls_run_id", "tool_calls", ["run_id"])
    op.create_table(
        "citation_snapshots",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("assistant_message_id", sa.String(length=128), nullable=False),
        sa.Column("paper_id", sa.String(length=64), nullable=True),
        sa.Column("paper_title", sa.String(length=1024), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("chunk_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_citation_snapshots_run_id", "citation_snapshots", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_citation_snapshots_run_id", table_name="citation_snapshots")
    op.drop_table("citation_snapshots")
    op.drop_index("ix_tool_calls_run_id", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_chunks_paper_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_ingestion_jobs_lease", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_claim", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_paper_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_table("conversations")
    op.drop_table("papers")
