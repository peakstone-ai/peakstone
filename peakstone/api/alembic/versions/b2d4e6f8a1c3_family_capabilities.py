"""model_families.capabilities (observed capabilities from public runs)

Revision ID: b2d4e6f8a1c3
Revises: a1c2d3e4f5a6
Create Date: 2026-06-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b2d4e6f8a1c3"
down_revision: Union[str, Sequence[str], None] = "a1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("model_families", sa.Column("capabilities", _JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("model_families", "capabilities")
