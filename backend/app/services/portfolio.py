"""Portfolio value: current market value, cost basis, unrealized gain (PRD T6), and a
value-over-time series from price history (PRD T8)."""
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.models import Card, CardVariant, CollectionItem, Set
from app.services.prices import get_current_prices


@dataclass(slots=True)
class PortfolioSummary:
    collection_id: int
    total_market_value: Decimal
    total_cost_basis: Decimal
    unrealized_gain: Decimal
    item_count: int
    priced_item_count: int
    price_date: str | None


def get_portfolio_summary(db: Session, collection_id: int) -> PortfolioSummary:
    items = list(
        db.execute(
            select(CollectionItem).where(CollectionItem.collection_id == collection_id)
        ).scalars()
    )
    empty = PortfolioSummary(collection_id, Decimal("0"), Decimal("0"), Decimal("0"), 0, 0, None)
    if not items:
        return empty

    variant_ids = [i.card_variant_id for i in items]
    variants = {
        v.id: v
        for v in db.execute(
            select(CardVariant).where(CardVariant.id.in_(variant_ids))
        ).scalars()
    }
    product_ids = sorted(
        {v.tcgplayer_product_id for v in variants.values() if v.tcgplayer_product_id}
    )
    prices = get_current_prices(db, product_ids)

    total_value = Decimal("0")
    total_cost = Decimal("0")
    price_date: str | None = None
    priced_item_count = 0
    for item in items:
        variant = variants.get(item.card_variant_id)
        if (
            variant is not None
            and variant.tcgplayer_product_id is not None
            and variant.tcgplayer_sub_type_name is not None
        ):
            price = prices.get((variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name))
            if price and price["market"] is not None:
                total_value += price["market"] * item.quantity
                priced_item_count += 1
                if price_date is None:
                    price_date = price["observed_on"]
        if item.acquired_price is not None:
            total_cost += item.acquired_price * item.quantity

    return PortfolioSummary(
        collection_id=collection_id,
        total_market_value=total_value,
        total_cost_basis=total_cost,
        unrealized_gain=total_value - total_cost,
        item_count=len(items),
        priced_item_count=priced_item_count,
        price_date=price_date,
    )


@dataclass(slots=True)
class PortfolioValuePoint:
    observed_on: str
    total_market_value: Decimal


def get_portfolio_value_history(db: Session, collection_id: int) -> list[PortfolioValuePoint]:
    """Value of the *current* holdings, priced at every date price history has data for.

    This is not a record of what was owned on each past date -- collection_item only tracks
    current quantity, not a history of changes (see docs/02-data-model.md) -- so this answers
    "what would today's collection have been worth on each past date", which is what PRD T8's
    "value history... a real time series" means given that data model.
    """
    items = list(
        db.execute(
            select(CollectionItem).where(CollectionItem.collection_id == collection_id)
        ).scalars()
    )
    if not items:
        return []

    variant_ids = [i.card_variant_id for i in items]
    variants = {
        v.id: v
        for v in db.execute(select(CardVariant).where(CardVariant.id.in_(variant_ids))).scalars()
    }
    qty_by_key: dict[tuple[int, str], int] = {}
    for item in items:
        variant = variants.get(item.card_variant_id)
        if (
            variant is None
            or variant.tcgplayer_product_id is None
            or variant.tcgplayer_sub_type_name is None
        ):
            continue
        key = (variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name)
        qty_by_key[key] = qty_by_key.get(key, 0) + item.quantity
    if not qty_by_key:
        return []

    product_ids = sorted({k[0] for k in qty_by_key})
    # Not deduplicating by source: only tcgcsv is ingested today (see docs/03-data-sources.md),
    # so (product_id, sub_type_name, observed_on) is effectively unique in practice. If a second
    # source is ever ingested for the same dates this would double-count and needs a preference
    # order, same as current_price would.
    stmt = text(
        "SELECT tcgplayer_product_id, sub_type_name, observed_on, market FROM price_point "
        "WHERE tcgplayer_product_id IN :product_ids AND market IS NOT NULL"
    ).bindparams(bindparam("product_ids", expanding=True))
    rows = db.execute(stmt, {"product_ids": product_ids}).mappings().all()

    value_by_date: dict[str, Decimal] = {}
    for row in rows:
        key = (row["tcgplayer_product_id"], row["sub_type_name"])
        qty = qty_by_key.get(key)
        if qty is None:
            continue
        observed_on = str(row["observed_on"])
        market = Decimal(str(row["market"]))
        value_by_date[observed_on] = value_by_date.get(observed_on, Decimal("0")) + market * qty

    return [
        PortfolioValuePoint(observed_on=d, total_market_value=value_by_date[d])
        for d in sorted(value_by_date)
    ]


class HoldingGroupKey(StrEnum):
    """A field the holdings list may treat as making a holding distinct.

    `collection_item` is one row per physical card, so a roll-up needs to be told what counts as
    "the same card". The card variant is always part of the key -- merging a Holofoil with a
    Normal would make `market_price` meaningless, since price identity is
    (tcgplayer_product_id, sub_type_name) and not the card (docs/02-data-model.md). Everything
    else is the caller's choice.

    Including LOCATION gives one row per physical slot: the fully expanded view of the shelf,
    where fifteen copies of a card in fifteen slots are fifteen rows. Leaving it out is the
    library view -- one row saying you own fifteen.
    """

    CONDITION = "condition"
    LANGUAGE = "language"
    GRADED = "graded"
    GRADE = "grade"
    LOCATION = "location"


# The historical shape of this table: one row per distinct holding, quantity on top. Deliberately
# excludes LOCATION, and mirrors the `collection_holding` view's GROUP BY (test_portfolio.py
# asserts the two agree, which is what keeps the view honest).
DEFAULT_GROUP_KEYS: frozenset[HoldingGroupKey] = frozenset(
    {
        HoldingGroupKey.CONDITION,
        HoldingGroupKey.LANGUAGE,
        HoldingGroupKey.GRADED,
        HoldingGroupKey.GRADE,
    }
)


@dataclass(slots=True)
class HoldingRow:
    """One holding, flattened for the holdings table.

    A row is a *group* of physical cards, not necessarily one card: what makes two copies the same
    holding is the `group_by` set the caller chose. With HoldingGroupKey.LOCATION in that set every
    physical slot is its own row; without it, fifteen copies collapse into one row of quantity 15.

    Everything the table can sort, filter or search on is resolved here rather than in the UI, so
    the CLI and the browser rank the same collection the same way. `market_price` is the unit
    price; `market_value` is that times quantity, which is what the totals are built from.

    `item_id` is the first underlying `collection_item` row, which is what a single-row edit or
    delete acts on; `item_ids` is all of them, so a caller that means "delete all fifteen" can.
    `storage_location` is set only when the group agrees on one -- `locations` always has the
    full list, and a UI should prefer it once `copies` exceeds one.
    """

    item_id: int
    item_ids: list[int]
    copies: int
    locations: list[str]
    card_variant_id: int
    card_id: int
    ptcg_card_id: str
    name: str
    number: str
    number_sort: int
    set_id: int
    set_name: str
    ptcg_set_id: str
    rarity: str | None
    variant: str
    condition: str
    language: str
    quantity: int
    is_graded: bool
    grade: str | None
    storage_location: str | None
    acquired_price: Decimal | None
    market_price: Decimal | None
    market_value: Decimal | None
    image_small: str | None


def list_holdings(
    db: Session,
    collection_id: int,
    group_by: Iterable[HoldingGroupKey] | None = None,
) -> list[HoldingRow]:
    """Every owned card joined to its card, set and current market price.

    `group_by` chooses what makes two physical cards the same holding; None means
    DEFAULT_GROUP_KEYS, the one-row-per-distinct-holding shape this table has always had. The card
    variant is always part of the key. Pass an empty set to group by variant alone, or include
    HoldingGroupKey.LOCATION to expand every physical slot into its own row.

    Returns the whole collection in one query rather than paging: this is a local-first tool with
    a collection in the low thousands, and handing the client the full list lets it sort and
    filter without a round trip per keystroke. Revisit if collections reach a size where the
    payload hurts.

    The grouping is done here rather than by reading the `collection_holding` view because this
    needs the card/set joins and current prices anyway, and one code path is easier to keep
    correct than two. The view is the SQL-level equivalent for ad-hoc queries; test_portfolio.py
    asserts the two agree on the default keys.
    """
    keys = DEFAULT_GROUP_KEYS if group_by is None else frozenset(group_by)
    rows = db.execute(
        select(CollectionItem, CardVariant, Card, Set)
        .join(CardVariant, CollectionItem.card_variant_id == CardVariant.id)
        .join(Card, CardVariant.card_id == Card.id)
        .join(Set, Card.set_id == Set.id)
        .where(CollectionItem.collection_id == collection_id)
        .order_by(Set.release_date.desc(), Card.number_sort, Card.number)
    ).all()

    product_ids = sorted({v.tcgplayer_product_id for _, v, _, _ in rows if v.tcgplayer_product_id})
    prices = get_current_prices(db, product_ids)

    holdings: dict[tuple[object, ...], HoldingRow] = {}
    for item, variant, card, set_row in rows:
        market: Decimal | None = None
        if variant.tcgplayer_product_id is not None and variant.tcgplayer_sub_type_name is not None:
            current = prices.get((variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name))
            if current:
                market = current["market"]

        group = _group_key(item, variant, keys)
        existing = holdings.get(group)
        if existing is None:
            holdings[group] = HoldingRow(
                item_id=item.id,
                item_ids=[item.id],
                copies=1,
                locations=[item.storage_location] if item.storage_location else [],
                card_variant_id=variant.id,
                card_id=card.id,
                ptcg_card_id=card.ptcg_card_id,
                name=card.name,
                number=card.number,
                number_sort=card.number_sort,
                set_id=set_row.id,
                set_name=set_row.name,
                ptcg_set_id=set_row.ptcg_set_id,
                rarity=card.rarity,
                variant=str(variant.variant),
                condition=str(item.condition),
                language=item.language,
                quantity=item.quantity,
                is_graded=item.is_graded,
                grade=item.grade,
                storage_location=item.storage_location,
                acquired_price=item.acquired_price,
                market_price=market,
                market_value=(market * item.quantity) if market is not None else None,
                image_small=card.image_small,
            )
            continue

        existing.item_ids.append(item.id)
        existing.copies += 1
        existing.quantity += item.quantity
        if item.storage_location and item.storage_location not in existing.locations:
            existing.locations.append(item.storage_location)
        # Only claim a location when the whole group is in one place; `locations` keeps the rest.
        if existing.storage_location != item.storage_location:
            existing.storage_location = None
        # Cost basis is a total across the group, so a partly-known basis is still worth showing.
        if item.acquired_price is not None:
            existing.acquired_price = (existing.acquired_price or Decimal("0")) + (
                item.acquired_price * item.quantity
            )
        if market is not None:
            existing.market_value = (existing.market_value or Decimal("0")) + market * item.quantity

    return list(holdings.values())


def _group_key(
    item: CollectionItem, variant: CardVariant, keys: frozenset[HoldingGroupKey]
) -> tuple[object, ...]:
    """The identity of a holding under `keys`. The variant is always in it -- see
    HoldingGroupKey."""
    key: list[object] = [variant.id]
    if HoldingGroupKey.CONDITION in keys:
        key.append(str(item.condition))
    if HoldingGroupKey.LANGUAGE in keys:
        key.append(item.language)
    if HoldingGroupKey.GRADED in keys:
        key.append(item.is_graded)
    if HoldingGroupKey.GRADE in keys:
        key.append(item.grade)
    if HoldingGroupKey.LOCATION in keys:
        # The row id keeps two cards in the same slot -- which the partial unique index forbids,
        # but an in-memory caller could still construct -- from merging.
        key.append(item.storage_location or f"#{item.id}")
    return tuple(key)
