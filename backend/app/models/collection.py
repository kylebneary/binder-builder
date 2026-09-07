"""User holdings and collecting goals."""
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import Condition, GoalType


class Collection(Base, TimestampMixin):
    __tablename__ = "collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="My Collection")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)


class CollectionItem(Base, TimestampMixin):
    """One row per *physical* card, not per distinct holding.

    A collector who owns fifteen copies of the same card has fifteen rows, because each copy sits
    in its own physical slot and a single row can hold only one `storage_location`. Quantity is
    rolled up on read -- by the `collection_holding` view for the default grouping, or by
    `services/portfolio.list_holdings(group_by=...)` for a caller-chosen one.

    `quantity` stays on the row for copies that are genuinely indistinguishable: an import whose
    file carries an explicit quantity column and no location (Collectr, Deckbox) writes one row of
    quantity N rather than fabricating N locations it does not know. So a roll-up is always
    SUM(quantity), never COUNT(*).

    Identity for an upsert is the physical slot -- `(collection_id, storage_location)` -- whenever
    a location is known, which is what makes re-importing the same file idempotent instead of
    duplicating every row. Rows without a location fall back to the old natural key. See
    `services/collection.upsert_collection_item` and docs/02-data-model.md.
    """

    __tablename__ = "collection_item"
    __table_args__ = (
        # One physical slot holds one card. Partial so the many rows with no recorded location do
        # not all collide on NULL; the syntax is the same on SQLite and Postgres.
        Index(
            "uq_collection_item_slot",
            "collection_id",
            "storage_location",
            unique=True,
            sqlite_where=text("storage_location IS NOT NULL"),
            postgresql_where=text("storage_location IS NOT NULL"),
        ),
        Index("ix_collection_item_variant", "collection_id", "card_variant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collection.id", ondelete="CASCADE"))
    card_variant_id: Mapped[int] = mapped_column(
        ForeignKey("card_variant.id", ondelete="CASCADE")
    )
    quantity: Mapped[int] = mapped_column(default=1)
    condition: Mapped[Condition] = mapped_column(String(8), default=Condition.NM)
    language: Mapped[str] = mapped_column(String(8), default="EN")
    is_graded: Mapped[bool] = mapped_column(Boolean, default=False)
    grader: Mapped[str | None] = mapped_column(String(16))
    grade: Mapped[str | None] = mapped_column(String(8))
    acquired_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    acquired_on: Mapped[date | None] = mapped_column(Date)
    storage_location: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(512))


class SealedHolding(Base, TimestampMixin):
    __tablename__ = "sealed_holding"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collection.id", ondelete="CASCADE"))
    sealed_product_id: Mapped[int] = mapped_column(
        ForeignKey("sealed_product.id", ondelete="CASCADE")
    )
    quantity: Mapped[int] = mapped_column(default=1)
    acquired_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    acquired_on: Mapped[date | None] = mapped_column(Date)
    is_opened: Mapped[bool] = mapped_column(Boolean, default=False)


class Goal(Base, TimestampMixin):
    __tablename__ = "goal"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    goal_type: Mapped[GoalType] = mapped_column(String(16))
    set_id: Mapped[int | None] = mapped_column(ForeignKey("set.id", ondelete="CASCADE"))
    filter_json: Mapped[dict | None] = mapped_column(JSON)
    target_condition: Mapped[Condition] = mapped_column(String(8), default=Condition.NM)


class GoalItem(Base):
    """Materialised need list. Kept flat so the optimizer can join, not evaluate filters."""

    __tablename__ = "goal_item"
    __table_args__ = (UniqueConstraint("goal_id", "card_variant_id", name="uq_goal_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goal.id", ondelete="CASCADE"))
    card_variant_id: Mapped[int] = mapped_column(
        ForeignKey("card_variant.id", ondelete="CASCADE")
    )
    required_qty: Mapped[int] = mapped_column(default=1)
