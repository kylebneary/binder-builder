from datetime import date

from app.models import Card, CardVariant, Collection, CollectionItem, PricePoint, Set
from app.models.enums import Variant
from app.services.sets import get_set_detail, list_sets


def _seed(db) -> tuple[Set, Card, Card, Collection]:
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", release_date=date(2024, 11, 8))
    db.add(set_row)
    db.flush()

    diglett = Card(
        ptcg_card_id="sv8-122",
        set_id=set_row.id,
        number="122",
        number_sort=122,
        name="Alolan Diglett",
        rarity="Common",
    )
    dugtrio = Card(
        ptcg_card_id="sv8-123",
        set_id=set_row.id,
        number="123",
        number_sort=123,
        name="Alolan Dugtrio",
        rarity="Uncommon",
    )
    db.add_all([diglett, dugtrio])
    db.flush()

    db.add_all(
        [
            CardVariant(
                card_id=diglett.id,
                variant=Variant.NORMAL,
                tcgplayer_product_id=589855,
                tcgplayer_sub_type_name="Normal",
                is_canonical=True,
            ),
            CardVariant(
                card_id=diglett.id,
                variant=Variant.REVERSE_HOLOFOIL,
                tcgplayer_product_id=589855,
                tcgplayer_sub_type_name="Reverse Holofoil",
                is_canonical=False,
            ),
            CardVariant(
                card_id=dugtrio.id,
                variant=Variant.NORMAL,
                tcgplayer_product_id=589856,
                tcgplayer_sub_type_name="Normal",
                is_canonical=True,
            ),
        ]
    )
    db.add_all(
        [
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=0.06,
            ),
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Reverse Holofoil",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=0.19,
            ),
            PricePoint(
                tcgplayer_product_id=589856,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=0.06,
            ),
        ]
    )
    collection = Collection(name="My Collection", is_default=True)
    db.add(collection)
    db.commit()
    return set_row, diglett, dugtrio, collection


def test_list_sets_returns_seeded_set(db):
    _seed(db)
    result = list_sets(db)
    assert [s.ptcg_set_id for s in result] == ["sv8"]


def test_get_set_detail_unknown_set_returns_none(db):
    assert get_set_detail(db, "does-not-exist", collection_id=1) is None


def test_get_set_detail_attaches_prices_and_ordering(db):
    _set_row, _diglett, _dugtrio, collection = _seed(db)
    detail = get_set_detail(db, "sv8", collection.id)
    assert detail is not None
    assert [c.number for c in detail.cards] == ["122", "123"]

    diglett_view = detail.cards[0]
    prices_by_variant = {v.tcgplayer_sub_type_name: v.market_price for v in diglett_view.variants}
    assert prices_by_variant["Normal"] == prices_by_variant["Normal"]  # sanity: no crash
    from decimal import Decimal

    assert prices_by_variant["Normal"] == Decimal("0.06")
    assert prices_by_variant["Reverse Holofoil"] == Decimal("0.19")


def test_get_set_detail_owned_needed_counts(db):
    _set_row, diglett, _dugtrio, collection = _seed(db)
    normal_variant = next(v for v in diglett.variants if v.variant == Variant.NORMAL)
    db.add(
        CollectionItem(
            collection_id=collection.id,
            card_variant_id=normal_variant.id,
            quantity=2,
            condition="NM",
            language="EN",
        )
    )
    db.commit()

    detail = get_set_detail(db, "sv8", collection.id)
    assert detail is not None
    assert detail.owned_count == 1
    assert detail.needed_count == 1

    diglett_view = next(c for c in detail.cards if c.ptcg_card_id == "sv8-122")
    assert diglett_view.is_owned is True
    normal_view = next(v for v in diglett_view.variants if v.tcgplayer_sub_type_name == "Normal")
    assert normal_view.owned_quantity == 2

    dugtrio_view = next(c for c in detail.cards if c.ptcg_card_id == "sv8-123")
    assert dugtrio_view.is_owned is False
