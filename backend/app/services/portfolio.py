"""Portfolio value: current market value, cost basis, unrealized gain (PRD T6)."""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CardVariant, CollectionItem
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
