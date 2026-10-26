"""Placeholder `unpriced` printings for cards with no card_variant

Data-only. A card the price feed hasn't priced had no card_variant, so it couldn't go in a goal or
a binder. From here on card ingest gives such cards one `unpriced` placeholder (see
app/ingest/placeholders.py); this backfills the cards already in the database. The price ingest
replaces each placeholder once a real printing exists.

Downgrade deletes the placeholders, and with them (ON DELETE CASCADE) any collection or goal rows
pointing at one.

Revision ID: e4b7c2a9d1f3
Revises: d3a8f1c6b905
"""
import sqlalchemy as sa
from alembic import op

revision = "e4b7c2a9d1f3"
down_revision = "d3a8f1c6b905"
branch_labels = None
depends_on = None

card = sa.table("card", sa.column("id", sa.Integer))
card_variant = sa.table(
    "card_variant",
    sa.column("id", sa.Integer),
    sa.column("card_id", sa.Integer),
    sa.column("variant", sa.String),
    sa.column("is_canonical", sa.Boolean),
    sa.column("is_special", sa.Boolean),
)


def upgrade() -> None:
    no_variant = ~sa.exists().where(card_variant.c.card_id == card.c.id)
    op.execute(
        card_variant.insert().from_select(
            ["card_id", "variant", "is_canonical", "is_special"],
            sa.select(
                card.c.id,
                sa.literal("unpriced"),
                sa.true(),
                sa.false(),
            ).where(no_variant),
        )
    )


def downgrade() -> None:
    op.execute(card_variant.delete().where(card_variant.c.variant == "unpriced"))
