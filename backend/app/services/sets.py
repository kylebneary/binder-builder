"""Set browsing: list sets, and a set's detail grid with owned quantity + current price per
variant. Returns plain dataclasses (not ORM objects, not Pydantic) so this stays reusable from
the CLI or tests without pulling in FastAPI -- see the layer rules in docs/01-architecture.md.
"""
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Card, CardVariant, CollectionItem, Set
from app.services.prices import get_current_prices


@dataclass(slots=True)
class VariantView:
    id: int
    variant: str
    tcgplayer_product_id: int | None
    tcgplayer_sub_type_name: str | None
    is_canonical: bool
    market_price: Decimal | None
    owned_quantity: int


@dataclass(slots=True)
class CardView:
    id: int
    ptcg_card_id: str
    number: str
    number_sort: int
    name: str
    supertype: str | None
    rarity: str | None
    artist: str | None
    image_small: str | None
    image_large: str | None
    variants: list[VariantView] = field(default_factory=list)

    @property
    def is_owned(self) -> bool:
        """Owned if any canonical variant has quantity > 0 -- master-set completion is a
        separate question the goal/optimizer layer answers per-variant, not per-card."""
        return any(v.owned_quantity > 0 for v in self.variants if v.is_canonical)


@dataclass(slots=True)
class SetView:
    id: int
    ptcg_set_id: str
    name: str
    series: str | None
    printed_total: int | None
    total: int | None
    release_date: date | None
    symbol_url: str | None
    logo_url: str | None


@dataclass(slots=True)
class SetDetailView(SetView):
    cards: list[CardView] = field(default_factory=list)
    owned_count: int = 0
    needed_count: int = 0


def _to_set_view(row: Set) -> SetView:
    return SetView(
        id=row.id,
        ptcg_set_id=row.ptcg_set_id,
        name=row.name,
        series=row.series,
        printed_total=row.printed_total,
        total=row.total,
        release_date=row.release_date,
        symbol_url=row.symbol_url,
        logo_url=row.logo_url,
    )


def list_sets(db: Session) -> list[SetView]:
    rows = db.execute(
        select(Set).order_by(Set.release_date.desc().nulls_last(), Set.name)
    ).scalars()
    return [_to_set_view(row) for row in rows]


def get_set_detail(db: Session, ptcg_set_id: str, collection_id: int) -> SetDetailView | None:
    set_row = db.execute(
        select(Set)
        .where(Set.ptcg_set_id == ptcg_set_id)
        .options(selectinload(Set.cards).selectinload(Card.variants))
    ).scalar_one_or_none()
    if set_row is None:
        return None

    all_variants: list[CardVariant] = [v for c in set_row.cards for v in c.variants]
    product_ids = sorted({v.tcgplayer_product_id for v in all_variants if v.tcgplayer_product_id})
    prices = get_current_prices(db, product_ids)

    variant_ids = [v.id for v in all_variants]
    owned_by_variant: dict[int, int] = {}
    if variant_ids:
        rows = db.execute(
            select(CollectionItem.card_variant_id, CollectionItem.quantity).where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.card_variant_id.in_(variant_ids),
            )
        ).all()
        for card_variant_id, qty in rows:
            owned_by_variant[card_variant_id] = owned_by_variant.get(card_variant_id, 0) + qty

    cards = sorted(set_row.cards, key=lambda c: (c.number_sort, c.number))
    card_views = []
    owned_count = 0
    for card in cards:
        variant_views = []
        card_owned = False
        for v in card.variants:
            price = None
            if v.tcgplayer_product_id is not None and v.tcgplayer_sub_type_name is not None:
                price = prices.get((v.tcgplayer_product_id, v.tcgplayer_sub_type_name))
            qty = owned_by_variant.get(v.id, 0)
            if v.is_canonical and qty > 0:
                card_owned = True
            variant_views.append(
                VariantView(
                    id=v.id,
                    variant=str(v.variant),
                    tcgplayer_product_id=v.tcgplayer_product_id,
                    tcgplayer_sub_type_name=v.tcgplayer_sub_type_name,
                    is_canonical=v.is_canonical,
                    market_price=price["market"] if price else None,
                    owned_quantity=qty,
                )
            )
        if card_owned:
            owned_count += 1
        card_views.append(
            CardView(
                id=card.id,
                ptcg_card_id=card.ptcg_card_id,
                number=card.number,
                number_sort=card.number_sort,
                name=card.name,
                supertype=card.supertype,
                rarity=card.rarity,
                artist=card.artist,
                image_small=card.image_small,
                image_large=card.image_large,
                variants=variant_views,
            )
        )

    base = _to_set_view(set_row)
    return SetDetailView(
        **asdict(base),
        cards=card_views,
        owned_count=owned_count,
        needed_count=len(card_views) - owned_count,
    )
