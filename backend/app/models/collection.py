"""User holdings and collecting goals."""
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import Condition, GoalType


class Collection(Base, TimestampMixin):
    __tablename__ = "collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="My Collection")
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)


class CollectionItem(Base, TimestampMixin):
    """One row per distinct holding; quantity on top of that."""

    __tablename__ = "collection_item"
    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "card_variant_id",
            "condition",
            "language",
            "is_graded",
            "grade",
            name="uq_collection_item",
        ),
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
