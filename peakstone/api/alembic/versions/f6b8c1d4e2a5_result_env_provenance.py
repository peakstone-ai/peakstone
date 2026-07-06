"""results.env — goal-state-env provider provenance (review R7): a local-provider agentic run
must be distinguishable from a faithful (docker/microvm) one on the public board

Revision ID: f6b8c1d4e2a5
Revises: e5a7b9c3d2f4
Create Date: 2026-07-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6b8c1d4e2a5"
down_revision: Union[str, Sequence[str], None] = "e5a7b9c3d2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("results", sa.Column(
        "env", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True))


def downgrade() -> None:
    op.drop_column("results", "env")
