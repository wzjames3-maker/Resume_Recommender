"""add content idempotency unique index on parse_runs

Revision ID: a64f7734c382
Revises: efe269148628
Create Date: 2026-08-09 15:34:43.837469

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a64f7734c382'
down_revision: Union[str, Sequence[str], None] = 'efe269148628'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('uq_parse_runs_content', 'parse_runs', ['workspace_id', 'file_hash', 'template_version', 'source_channel'],
                    unique=True, postgresql_nulls_not_distinct=True,
                    postgresql_where=sa.text("status NOT IN ('failed', 'dead_letter')"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_parse_runs_content', table_name='parse_runs',
                  postgresql_where=sa.text("status NOT IN ('failed', 'dead_letter')"))