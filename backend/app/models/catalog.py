"""Card catalogue: sets, cards, printing variants, sealed products, prices."""
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ProductType, Variant


class Set(Base, TimestampMixin):
    __tablename__ = "set"

    id: Mapped[int] = mapped_column(primary_key=True)
    ptcg_set_id: Mapped[str] = mapped_column(String(32), unique=True)
    tcgplayer_group_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(128))
    series: Mapped[str | None] = mapped_column(String(64))
    printed_total: Mapped[int | None]
    total: Mapped[int | None]
    release_date: Mapped[date | None] = mapped_column(Date)
    ptcgo_code: Mapped[str | None] = mapped_column(String(16))
    symbol_url: Mapped[str | None] = mapped_column(String(512))
    logo_url: Mapped[str | None] = mapped_column(String(512))

    cards: Mapped[list["Card"]] = relationship(back_populates="set")


class Card(Base, TimestampMixin):
    __tablename__ = "card"
    __table_args__ = (Index("ix_card_set_number", "set_id", "number_sort"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("set.id", ondelete="CASCADE"))
    ptcg_card_id: Mapped[str] = mapped_column(String(64), unique=True)
    # Text, not int: "TG12", "SV045", "H31", "025a" all occur.
    number: Mapped[str] = mapped_column(String(16))
    number_sort: Mapped[int] = mapped_column(default=0)
    name: Mapped[str] = mapped_column(String(128))
    supertype: Mapped[str | None] = mapped_column(String(32))
    rarity: Mapped[str | None] = mapped_column(String(64))
    artist: Mapped[str | None] = mapped_column(String(128))
    subtypes: Mapped[list | None] = mapped_column(JSON)
    types: Mapped[list | None] = mapped_column(JSON)
    national_pokedex_numbers: Mapped[list | None] = mapped_column(JSON)
    image_small: Mapped[str | None] = mapped_column(String(512))
    image_large: Mapped[str | None] = mapped_column(String(512))
    # Cached dominant colour in CIELAB, used by the Michi auto-layout scorer.
    dominant_color_lab: Mapped[list | None] = mapped_column(JSON)

    set: Mapped[Set] = relationship(back_populates="cards")
    variants: Mapped[list["CardVariant"]] = relationship(back_populates="card")


class CardVariant(Base, TimestampMixin):
    """A specific printing of a card. THE pricing and ownership unit -- see docs/02-data-model.md.

    Which variants exist is derived from the price feed (one row per subTypeName tcgcsv
    returns for the product), never assumed from the card's rarity.
    """

    __tablename__ = "card_variant"
    __table_args__ = (
        UniqueConstraint("card_id", "variant", name="uq_card_variant"),
        Index("ix_variant_product", "tcgplayer_product_id", "tcgplayer_sub_type_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"))
    variant: Mapped[Variant] = mapped_column(String(32))
    tcgplayer_product_id: Mapped[int | None]
    tcgplayer_sub_type_name: Mapped[str | None] = mapped_column(String(64))
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)

    card: Mapped[Card] = relationship(back_populates="variants")


class SealedProduct(Base, TimestampMixin):
    __tablename__ = "sealed_product"

    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int | None] = mapped_column(ForeignKey("set.id", ondelete="SET NULL"))
    tcgplayer_product_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(256))
    product_type: Mapped[ProductType] = mapped_column(String(32), default=ProductType.OTHER)
    packs_per_unit: Mapped[int | None]
    pack_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("pull_rate_profile.id", ondelete="SET NULL")
    )
    msrp: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    contains_promos: Mapped[bool] = mapped_column(Boolean, default=False)
    image_url: Mapped[str | None] = mapped_column(String(512))


class PricePoint(Base):
    """Daily price observation, keyed the way the source keys it."""

    __tablename__ = "price_point"
    __table_args__ = (
        UniqueConstraint(
            "tcgplayer_product_id",
            "sub_type_name",
            "observed_on",
            "source",
            name="uq_price_point",
        ),
        Index("ix_price_observed_on", "observed_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tcgplayer_product_id: Mapped[int]
    sub_type_name: Mapped[str] = mapped_column(String(64))
    observed_on: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), default="tcgcsv")
    low: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    mid: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    high: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    market: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    direct_low: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
