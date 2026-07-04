"""commit-and-reveal: private/commitment/revealed on results + the reveals table

Revision ID: d4f6a8b2c1e3
Revises: c3e5f7a9b1d2
Create Date: 2026-07-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4f6a8b2c1e3"
down_revision: Union[str, Sequence[str], None] = "c3e5f7a9b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("results", sa.Column("private", sa.Boolean(), nullable=False,
                                       server_default=sa.false()))
    op.add_column("results", sa.Column("commitment", sa.String(), nullable=True))
    op.add_column("results", sa.Column("revealed", sa.Boolean(), nullable=False,
                                       server_default=sa.false()))
    op.create_index(op.f("ix_results_private"), "results", ["private"])
    op.create_index(op.f("ix_results_commitment"), "results", ["commitment"])
    op.create_table(
        "reveals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commitment", sa.String(), nullable=False),
        sa.Column("salt", sa.String(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("files", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                  nullable=False),
        sa.Column("validation", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                  nullable=True),
        sa.Column("revealed_by_key_id", sa.Integer(), nullable=True),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"]),
        sa.ForeignKeyConstraint(["revealed_by_key_id"], ["keys.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reveals_commitment"), "reveals", ["commitment"], unique=True)
    op.create_index(op.f("ix_reveals_challenge_id"), "reveals", ["challenge_id"])


def downgrade() -> None:
    op.drop_table("reveals")
    op.drop_index(op.f("ix_results_commitment"), table_name="results")
    op.drop_index(op.f("ix_results_private"), table_name="results")
    op.drop_column("results", "revealed")
    op.drop_column("results", "commitment")
    op.drop_column("results", "private")
