"""contamination dates: model_families.training_cutoff + results.published_at

Revision ID: a1c2d3e4f5a6
Revises: 20932c8fcabd
Create Date: 2026-06-25 15:30:00.000000

Adds the date fields that drive the held-out (contamination-adjusted) metric:
a model's claimed training_cutoff, and per-result publish date + provenance.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "20932c8fcabd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("model_families", sa.Column("training_cutoff", sa.String(), nullable=True))
    op.add_column("results", sa.Column("published_at", sa.String(), nullable=True))
    op.add_column("results", sa.Column("published_at_source", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("results", "published_at_source")
    op.drop_column("results", "published_at")
    op.drop_column("model_families", "training_cutoff")
