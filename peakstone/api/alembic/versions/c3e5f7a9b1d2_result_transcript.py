"""result transcript: per-challenge model output (solution + execution output)

Revision ID: c3e5f7a9b1d2
Revises: b2d4e6f8a1c3
Create Date: 2026-06-26 00:00:00.000000

Stores each result's transcript (raw_output/stdout/stderr/plan + error type) so the
leaderboard can drill into a run and show the model's proposed solution and the test's
reaction. JSON column; nullable for back-compat with rows ingested before this.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3e5f7a9b1d2"
down_revision: Union[str, Sequence[str], None] = "b2d4e6f8a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("results", sa.Column("transcript", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("results", "transcript")
