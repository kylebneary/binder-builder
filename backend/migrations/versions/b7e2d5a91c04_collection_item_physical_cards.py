"""collection_item is one row per physical card

Drops the `uq_collection_item` natural key, so a collector who owns fifteen copies of a card can
hold fifteen rows -- one per physical slot, each with its own `storage_location`. Quantity moves
from being stored per distinct holding to being rolled up on read, by the `collection_holding`
view added here.

The new unique key is the physical slot, `(collection_id, storage_location)`, partial on
storage_location IS NOT NULL so the rows with no recorded location do not all collide. The same
`CREATE UNIQUE INDEX ... WHERE` syntax works on SQLite and Postgres.

Revision ID: b7e2d5a91c04
Revises: a1f4c9d7e2b3
"""
import sqlalchemy as sa
from alembic import op

revision = "b7e2d5a91c04"
down_revision = "a1f4c9d7e2b3"
branch_labels = None
depends_on = None


# SUM(quantity) rather than COUNT(*): a row whose import knew a quantity but no location stands
# for N indistinguishable copies, and counting rows would report it as one card.
COLLECTION_HOLDING_VIEW = """
CREATE VIEW collection_holding AS
SELECT
    collection_id,
    card_variant_id,
    condition,
    language,
    is_graded,
    grade,
    SUM(quantity) AS quantity,
    COUNT(*) AS copy_rows,
    COUNT(storage_location) AS located_copies,
    MIN(storage_location) AS first_location,
    SUM(acquired_price * quantity) AS acquired_total
FROM collection_item
GROUP BY collection_id, card_variant_id, condition, language, is_graded, grade
"""


def upgrade() -> None:
    # SQLite cannot drop a constraint in place; batch mode recreates the table and copies rows.
    with op.batch_alter_table("collection_item") as batch_op:
        batch_op.drop_constraint("uq_collection_item", type_="unique")

    op.create_index(
        "uq_collection_item_slot",
        "collection_item",
        ["collection_id", "storage_location"],
        unique=True,
        sqlite_where=sa.text("storage_location IS NOT NULL"),
        postgresql_where=sa.text("storage_location IS NOT NULL"),
    )
    # The old unique constraint was also the index every owned-lookup used; keep a non-unique one
    # so services/sets, goals, binder and simulate do not fall back to a scan.
    op.create_index(
        "ix_collection_item_variant",
        "collection_item",
        ["collection_id", "card_variant_id"],
    )
    op.execute(COLLECTION_HOLDING_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS collection_holding")
    op.drop_index("ix_collection_item_variant", table_name="collection_item")
    op.drop_index("uq_collection_item_slot", table_name="collection_item")
    # Restoring the unique constraint fails if duplicate physical rows exist -- collapse them
    # first, which is a data decision this migration will not make silently.
    with op.batch_alter_table("collection_item") as batch_op:
        batch_op.create_unique_constraint(
            "uq_collection_item",
            ["collection_id", "card_variant_id", "condition", "language", "is_graded", "grade"],
        )
