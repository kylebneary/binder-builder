"""card_variant.is_special: stamps and promo printings, for Grand Master Set goals

Tagged printings that TCGplayer sells as separate products (prerelease and staff stamps, Cosmos
holos, Worlds stamps, ...) become card_variant rows. They are counted by a Grand Master Set goal
but not a Master Set one, so the row records which kind it is. Every existing row is a base
printing, hence the false default.

Revision ID: d3a8f1c6b905
Revises: b7e2d5a91c04
"""
import sqlalchemy as sa
from alembic import op

revision = "d3a8f1c6b905"
down_revision = "b7e2d5a91c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("card_variant") as batch:
        batch.add_column(
            sa.Column("is_special", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("card_variant") as batch:
        batch.drop_column("is_special")
