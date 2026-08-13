"""add rejected and hired candidate pool statuses

Revision ID: 8fce2a1b3d4e
Revises: 7165970c22da
Create Date: 2026-08-08 12:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8fce2a1b3d4e'
down_revision: str | Sequence[str] | None = '7165970c22da'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE candidate_status ADD VALUE 'rejected'")
    op.execute("ALTER TYPE candidate_status ADD VALUE 'hired'")


def downgrade() -> None:
    """Downgrade schema."""
    # PG 不支持从 enum 删除值；下限仅记录（生产如需回退需重建 enum 类型）。
    pass