from datetime import date
from decimal import Decimal

from app.models import Card, CardVariant, PricePoint, Set
from app.models.enums import Variant
from app.services.collection import (
    CollectionItemData,
    get_or_create_default_collection,
    upsert_collection_item,
)
from app.services.portfolio import (
    HoldingGroupKey,
    get_portfolio_summary,
    get_portfolio_value_history,
    list_holdings,
)
from sqlalchemy import text


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


def test_value_history_empty_collection_returns_empty_list(db):
    collection = get_or_create_default_collection(db)
    assert get_portfolio_value_history(db, collection.id) == []


def test_value_history_prices_current_holdings_at_each_past_date(db):
    normal, reverse = _seed_two_variants(db)
    # A second, older price snapshot for the same products.
    db.add_all(
        [
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 20),
                source="tcgcsv",
                market=1.00,
            ),
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Reverse Holofoil",
                observed_on=date(2026, 8, 20),
                source="tcgcsv",
                market=20.00,
            ),
        ]
    )
    db.commit()

    collection = get_or_create_default_collection(db)
    upsert_collection_item(
        db, collection.id, CollectionItemData(card_variant_id=normal.id, quantity=4)
    )
    upsert_collection_item(
        db, collection.id, CollectionItemData(card_variant_id=reverse.id, quantity=1)
    )

    history = get_portfolio_value_history(db, collection.id)
    assert [p.observed_on for p in history] == ["2026-08-20", "2026-08-25"]
    # 2026-08-20: 4 * 1.00 + 1 * 20.00 = 24.00
    assert history[0].total_market_value == Decimal("24.00")
    # 2026-08-25 (from _seed_two_variants): 4 * 1.50 + 1 * 28.00 = 34.00
    assert history[1].total_market_value == Decimal("34.00")


def _own(db, variant, **kw):
    collection = get_or_create_default_collection(db)
    upsert_collection_item(
        db,
        collection.id,
        CollectionItemData(card_variant_id=variant.id, **kw),
    )
    return collection


def test_list_holdings_joins_card_set_and_price(db):
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, quantity=2)

    holdings = list_holdings(db, collection.id)
    assert len(holdings) == 1
    row = holdings[0]
    assert (row.set_name, row.name, row.number) == ("Surging Sparks", "Alolan Diglett", "122")
    assert row.market_price == Decimal("1.50")
    # market_value is the unit price times quantity -- what the shown-total sums.
    assert row.market_value == Decimal("3.00")


def test_list_holdings_separates_variants_of_the_same_card(db):
    """Two printings of one card are two holdings at two prices -- the price identity rule in
    docs/02-data-model.md, which a card-level table would flatten and misprice."""
    normal, reverse = _seed_two_variants(db)
    collection = _own(db, normal, quantity=1)
    _own(db, reverse, quantity=1)

    rows = {h.variant: h for h in list_holdings(db, collection.id)}
    assert set(rows) == {"normal", "reverse_holofoil"}
    assert rows["normal"].market_price == Decimal("1.50")
    assert rows["reverse_holofoil"].market_price == Decimal("28.00")


def test_list_holdings_carries_storage_location(db):
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, quantity=1, storage_location="Box 1 - A3")
    assert list_holdings(db, collection.id)[0].storage_location == "Box 1 - A3"


def test_list_holdings_keeps_zero_quantity_rows(db):
    """A deliberate zero-of-this-variant row is a real record, so the read model keeps it and the
    table's `owned only` filter is where that judgement belongs."""
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, quantity=0)

    rows = list_holdings(db, collection.id)
    assert len(rows) == 1
    assert rows[0].quantity == 0
    assert rows[0].market_value == Decimal("0.00")


def test_list_holdings_of_an_empty_collection_is_empty(db):
    collection = get_or_create_default_collection(db)
    assert list_holdings(db, collection.id) == []


# --- one row per physical card, rolled up on read ------------------------------------------------


def test_same_card_in_two_slots_is_two_rows(db):
    """The change that motivated all of this: a duplicate no longer overwrites its twin.

    Under the old natural key these two upserts collided and the second *set* quantity to 1,
    silently losing a card. See docs/07-data-backlog.md section 4.
    """
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, storage_location="Box 1 - A3")
    _own(db, normal, storage_location="Box 1 - A4")

    rows = list_holdings(db, collection.id, group_by=[HoldingGroupKey.LOCATION])
    assert len(rows) == 2
    assert sorted(r.storage_location for r in rows) == ["Box 1 - A3", "Box 1 - A4"]


def test_default_grouping_rolls_slots_into_one_holding(db):
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, storage_location="Box 1 - A3")
    _own(db, normal, storage_location="Box 1 - A4")

    rows = list_holdings(db, collection.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.quantity == 2
    assert row.copies == 2
    assert row.locations == ["Box 1 - A3", "Box 1 - A4"]
    # Value follows the roll-up: two copies at 1.50.
    assert row.market_value == Decimal("3.00")
    # No single location is true of the group, so the column stays empty rather than picking one.
    assert row.storage_location is None
    assert row.item_ids == sorted(row.item_ids) and len(row.item_ids) == 2


def test_a_group_in_one_place_keeps_its_location(db):
    """Collapsing is only lossy when the copies actually disagree."""
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, quantity=3, storage_location="Box 1 - A3")

    row = list_holdings(db, collection.id)[0]
    assert row.storage_location == "Box 1 - A3"
    assert (row.quantity, row.copies) == (3, 1)


def test_condition_can_be_dropped_from_the_key(db):
    """The point of a caller-chosen key: 'how many of this card do I own, any condition?'"""
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, condition="NM", storage_location="Box 1 - A3")
    _own(db, normal, condition="LP", storage_location="Box 1 - A4")

    assert len(list_holdings(db, collection.id)) == 2
    merged = list_holdings(db, collection.id, group_by=[])
    assert len(merged) == 1
    assert merged[0].quantity == 2


def test_variants_never_merge_however_few_keys_are_given(db):
    """Price identity is (product, sub_type), so merging variants would make market_price a lie."""
    normal, holo = _seed_two_variants(db)
    collection = _own(db, normal, storage_location="Box 1 - A3")
    _own(db, holo, storage_location="Box 1 - A4")

    assert len(list_holdings(db, collection.id, group_by=[])) == 2


def test_reimporting_the_same_slot_updates_it_rather_than_duplicating(db):
    """What makes re-running an import safe: the slot is the identity."""
    normal, holo = _seed_two_variants(db)
    collection = _own(db, normal, storage_location="Box 1 - A3")
    _own(db, normal, storage_location="Box 1 - A3")
    assert len(list_holdings(db, collection.id, group_by=[HoldingGroupKey.LOCATION])) == 1

    # And re-organising: a different card in that slot replaces what was there.
    _own(db, holo, storage_location="Box 1 - A3")
    rows = list_holdings(db, collection.id, group_by=[HoldingGroupKey.LOCATION])
    assert len(rows) == 1
    assert rows[0].card_variant_id == holo.id


def test_rows_without_a_location_still_key_on_the_natural_key(db):
    """A Collectr-shaped import knows quantity but no slot, and must not accumulate rows."""
    normal, _ = _seed_two_variants(db)
    collection = _own(db, normal, quantity=4)
    _own(db, normal, quantity=6)

    rows = list_holdings(db, collection.id)
    assert len(rows) == 1
    assert rows[0].quantity == 6


def test_collection_holding_view_agrees_with_the_default_grouping(db):
    """The view and the service are two implementations of one rule; keep them honest.

    The view is what ad-hoc SQL and any Postgres consumer see, but list_holdings does its own
    grouping (it needs the joins and prices anyway). If they ever disagree, one of them is lying
    to somebody.
    """
    normal, holo = _seed_two_variants(db)
    collection = _own(db, normal, storage_location="Box 1 - A3")
    _own(db, normal, storage_location="Box 1 - A4")
    _own(db, normal, condition="LP", storage_location="Box 2 - B1")
    _own(db, holo, quantity=5)

    view_rows = {
        (r.card_variant_id, r.condition, r.language, bool(r.is_graded), r.grade): r.quantity
        for r in db.execute(
            text(
                "SELECT card_variant_id, condition, language, is_graded, grade, quantity "
                "FROM collection_holding WHERE collection_id = :cid"
            ),
            {"cid": collection.id},
        )
    }
    service_rows = {
        (h.card_variant_id, h.condition, h.language, h.is_graded, h.grade): h.quantity
        for h in list_holdings(db, collection.id)
    }
    assert view_rows == service_rows
    assert sum(view_rows.values()) == 8
