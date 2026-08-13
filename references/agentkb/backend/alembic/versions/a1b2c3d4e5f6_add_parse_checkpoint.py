"""add parse checkpoint

Revision ID: a1b2c3d4e5f6
Revises: 3fc5f2ab57e8
Create Date: 2026-08-08 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '3fc5f2ab57e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('parse_checkpoints',
    sa.Column('run_id', sa.String(length=64), nullable=False),
    sa.Column('llm_candidate_enc', sa.Text(), nullable=False),
    sa.Column('llm_evidence', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('llm_profile', postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), 'sqlite'), nullable=False),
    sa.Column('pii_mapping_enc', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('run_id', name=op.f('pk_parse_checkpoints'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('parse_checkpoints')