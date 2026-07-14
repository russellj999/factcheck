"""add retrieval_jobs table

Revision ID: 0001_add_retrieval_jobs
Revises: None
Create Date: 2026-07-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_add_retrieval_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("ingest_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'::text")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_retrieval_jobs_ingest_id", "retrieval_jobs", ["ingest_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_retrieval_jobs_ingest_id", table_name="retrieval_jobs")
    op.drop_table("retrieval_jobs")
