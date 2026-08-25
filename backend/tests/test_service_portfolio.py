from datetime import date
from decimal import Decimal

from app.models import Card, CardVariant, PricePoint, Set
from app.models.enums import Variant
from app.services.collection import (
    CollectionItemData,
    get_or_create_default_collection,
    upsert_collection_item,
)
from app.services.portfolio import get_portfolio_summary


def _seed_two_variants(db) -> tuple[CardVariant, CardVariant]:
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks")
    db.add(set_row)
    db.flush()
    card = Card(
        ptcg_card_id="sv8-122",
        set_id=set_row.id,
        number="122",
        number_sort=122,
        name="Alolan Diglett",
    )
    db.add(card)
    db.flush()
    normal = CardVariant(
        card_id=card.id,
        variant=Variant.NORMAL,
        tcgplayer_product_id=589855,
        tcgplayer_sub_type_name="Normal",
        is_canonical=True,
    )
    reverse = CardVariant(
        card_id=card.id,
        variant=Variant.REVERSE_HOLOFOIL,
        tcgplayer_product_id=589855,
        tcgplayer_sub_type_name="Reverse Holofoil",
        is_canonical=False,
    )
    db.add_all([normal, reverse])
    db.add_all(
        [
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=1.50,
            ),
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Reverse Holofoil",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=28.00,
            ),
        ]
    )
    db.commit()
    return normal, reverse


def test_empty_collection_returns_zeroed_summary(db):
    collection = get_or_create_default_collection(db)
    summary = get_portfolio_summary(db, collection.id)
    assert summary.total_market_value == Decimal("0")
    assert summary.total_cost_basis == Decimal("0")
    assert summary.unrealized_gain == Decimal("0")
    assert summary.item_count == 0
    assert summary.price_date is None


def test_portfolio_value_sums_market_price_times_quantity(db):
    normal, reverse = _seed_two_variants(db)
    collection = get_or_create_default_collection(db)
    upsert_collection_item(
        db, collection.id, CollectionItemData(card_variant_id=normal.id, quantity=4)
    )
    upsert_collection_item(
        db, collection.id, CollectionItemData(card_variant_id=reverse.id, quantity=1)
    )

    summary = get_portfolio_summary(db, collection.id)
    # 4 * 1.50 + 1 * 28.00 = 34.00
    assert summary.total_market_value == Decimal("34.00")
    assert summary.item_count == 2
    assert summary.priced_item_count == 2
    assert summary.price_date == "2026-08-25"


def test_portfolio_cost_basis_and_gain(db):
    normal, _reverse = _seed_two_variants(db)
    collection = get_or_create_default_collection(db)
    upsert_collection_item(
        db,
        collection.id,
        CollectionItemData(card_variant_id=normal.id, quantity=4, acquired_price=Decimal("1.00")),
    )

    summary = get_portfolio_summary(db, collection.id)
    assert summary.total_market_value == Decimal("6.00")  # 4 * 1.50
    assert summary.total_cost_basis == Decimal("4.00")  # 4 * 1.00
    assert summary.unrealized_gain == Decimal("2.00")


def test_portfolio_handles_variant_with_no_price_gracefully(db):
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks")
    db.add(set_row)
    db.flush()
    card = Card(
        ptcg_card_id="sv8-1", set_id=set_row.id, number="1", number_sort=1, name="No Price Card"
    )
    db.add(card)
    db.flush()
    variant = CardVariant(card_id=card.id, variant=Variant.NORMAL, is_canonical=True)
    db.add(variant)
    db.commit()

    collection = get_or_create_default_collection(db)
    upsert_collection_item(
        db, collection.id, CollectionItemData(card_variant_id=variant.id, quantity=2)
    )

    summary = get_portfolio_summary(db, collection.id)
    assert summary.total_market_value == Decimal("0")
    assert summary.item_count == 1
    assert summary.priced_item_count == 0
