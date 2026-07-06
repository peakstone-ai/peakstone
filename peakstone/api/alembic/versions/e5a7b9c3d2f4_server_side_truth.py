"""server-side truth (review R2-R5): challenge_sightings table, family metadata_trust,
submission suite_hash_match

Revision ID: e5a7b9c3d2f4
Revises: d4f6a8b2c1e3
Create Date: 2026-07-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a7b9c3d2f4"
down_revision: Union[str, Sequence[str], None] = "d4f6a8b2c1e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # first-seen notarization of challenge content (clamps forgeable published_at claims)
    op.create_table(
        "challenge_sightings",
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("content_hash"),
    )
    # trust tier of the submission that last wrote family metadata (highest-trust-wins reconciliation)
    op.add_column("model_families", sa.Column("metadata_trust", sa.String(), nullable=True,
                                              server_default="self-reported"))
    # does the bundle's suite content_hash match the suite's first-seen hash (NULL = no basis)
    op.add_column("submissions", sa.Column("suite_hash_match", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("submissions", "suite_hash_match")
    op.drop_column("model_families", "metadata_trust")
    op.drop_table("challenge_sightings")
