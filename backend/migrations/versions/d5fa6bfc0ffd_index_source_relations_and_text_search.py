"""Index source relations and text search

Revision ID: d5fa6bfc0ffd
Revises: 1f43fe606299
Create Date: 2026-11-10 12:49:17.503233
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d5fa6bfc0ffd"
down_revision: Union[str, None] = "1f43fe606299"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_sources_original_source_id"), "sources", ["original_source_id"], unique=False
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_cases_claim_fts ON cases USING gin (to_tsvector('english', claim))"
        )
        op.execute(
            "CREATE INDEX ix_evidence_passage_fts ON evidence USING gin (to_tsvector('english', passage))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX ix_evidence_passage_fts")
        op.execute("DROP INDEX ix_cases_claim_fts")
    op.drop_index(op.f("ix_sources_original_source_id"), table_name="sources")
