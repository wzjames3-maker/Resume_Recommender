"""add interview result to assignments

Revision ID: 9c7e2a1b4d6f
Revises: 7ab6632c3c76
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c7e2a1b4d6f"
down_revision: Union[str, Sequence[str], None] = "7ab6632c3c76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE interview_result AS ENUM ('passed', 'failed', 'no_show', 'cancelled')")
    op.add_column("assignments", sa.Column("interview_result", sa.Enum(
        "passed", "failed", "no_show", "cancelled", name="interview_result",
        create_type=False), nullable=True))
    op.create_index("ix_assignments_interview_result", "assignments", ["interview_result"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_assignments_interview_result", table_name="assignments")
    op.drop_column("assignments", "interview_result")
    op.execute("DROP TYPE IF EXISTS interview_result")
