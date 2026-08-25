"""Pull-rate profiles. Source of truth is data/pull_rates/*.yaml; these tables are a cache."""
from datetime import date

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import Confidence


class PullRateProfile(Base, TimestampMixin):
    __tablename__ = "pull_rate_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int | None] = mapped_column(ForeignKey("set.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    cards_per_pack: Mapped[int] = mapped_column(default=10)
    source_urls: Mapped[list | None] = mapped_column(JSON)
    sample_packs: Mapped[int | None]
    confidence: Mapped[Confidence] = mapped_column(String(8), default=Confidence.LOW)
    notes: Mapped[str | None] = mapped_column(String(2048))
    effective_from: Mapped[date | None] = mapped_column(Date)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
    source_file: Mapped[str | None] = mapped_column(String(256))

    slots: Mapped[list["PackSlot"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    box_constraints: Mapped[list["BoxConstraint"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class PackSlot(Base):
    __tablename__ = "pack_slot"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("pull_rate_profile.id", ondelete="CASCADE")
    )
    slot_index: Mapped[int]
    label: Mapped[str] = mapped_column(String(64))
    repeat: Mapped[int] = mapped_column(default=1)

    profile: Mapped[PullRateProfile] = relationship(back_populates="slots")
    outcomes: Mapped[list["SlotOutcome"]] = relationship(
        back_populates="slot", cascade="all, delete-orphan"
    )


class SlotOutcome(Base):
    """Probabilities within a slot MUST sum to 1.0 +/- 1e-6. Validated at YAML load time."""

    __tablename__ = "slot_outcome"

    id: Mapped[int] = mapped_column(primary_key=True)
    pack_slot_id: Mapped[int] = mapped_column(ForeignKey("pack_slot.id", ondelete="CASCADE"))
    rarity: Mapped[str] = mapped_column(String(64))
    probability: Mapped[float] = mapped_column(Float)
    variant: Mapped[str] = mapped_column(String(32), default="normal")
    pool_filter_json: Mapped[dict | None] = mapped_column(JSON)

    slot: Mapped[PackSlot] = relationship(back_populates="outcomes")


class BoxConstraint(Base):
    """Collation guarantees. These break pack independence and force Monte Carlo."""

    __tablename__ = "box_constraint"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("pull_rate_profile.id", ondelete="CASCADE")
    )
    rarity: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(8), default="box")
    min_per_box: Mapped[int | None]
    max_per_box: Mapped[int | None]
    exact_per_box: Mapped[int | None]

    profile: Mapped[PullRateProfile] = relationship(back_populates="box_constraints")
