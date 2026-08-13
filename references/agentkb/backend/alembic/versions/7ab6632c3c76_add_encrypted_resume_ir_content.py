"""add encrypted resume ir content

Revision ID: 7ab6632c3c76
Revises: a64f7734c382
Create Date: 2026-08-09 10:11:49.508064

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7ab6632c3c76'
down_revision: str | Sequence[str] | None = 'a64f7734c382'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("resume_irs", sa.Column("content_enc", sa.Text(), nullable=True))
    op.alter_column("resume_irs", "content", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("resume_irs", "content", existing_type=sa.Text(), nullable=False)
    op.drop_column("resume_irs", "content_enc")
