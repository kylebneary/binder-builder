from datetime import date
from decimal import Decimal

from app.models import Card, CardVariant, Set
from app.models.enums import Variant
from app.services.collection import (
    CollectionItemData,
    delete_collection_item,
    get_or_create_default_collection,
    list_collection_items,
    upsert_collection_item,
)


def _seed_variant(db) -> CardVariant:
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
    variant = CardVariant(card_id=card.id, variant=Variant.NORMAL, is_canonical=True)
    db.add(variant)
    db.commit()
    return variant


def test_get_or_create_default_collection_is_idempotent(db):
    c1 = get_or_create_default_collection(db)
    c2 = get_or_create_default_collection(db)
    assert c1.id == c2.id


def test_upsert_collection_item_creates_then_updates_same_row(db):
    collection = get_or_create_default_collection(db)
    variant = _seed_variant(db)

    data = CollectionItemData(
        card_variant_id=variant.id, quantity=1, acquired_price=Decimal("5.00")
    )
    item1 = upsert_collection_item(db, collection.id, data)
    assert item1.quantity == 1

    # Same natural key (card_variant_id, condition, language, is_graded, grade) -> same row,
    # quantity updated in place, not a duplicate.
    data2 = CollectionItemData(
        card_variant_id=variant.id, quantity=4, acquired_price=Decimal("5.00")
    )
    item2 = upsert_collection_item(db, collection.id, data2)
    assert item2.id == item1.id
    assert item2.quantity == 4

    items = list_collection_items(db, collection.id)
    assert len(items) == 1


def test_upsert_collection_item_different_condition_is_a_different_row(db):
    collection = get_or_create_default_collection(db)
    variant = _seed_variant(db)

    data_nm = CollectionItemData(card_variant_id=variant.id, condition="NM")
    data_lp = CollectionItemData(card_variant_id=variant.id, condition="LP")
    upsert_collection_item(db, collection.id, data_nm)
    upsert_collection_item(db, collection.id, data_lp)

    items = list_collection_items(db, collection.id)
    assert {i.condition for i in items} == {"NM", "LP"}


def test_delete_collection_item(db):
    collection = get_or_create_default_collection(db)
    variant = _seed_variant(db)
    item = upsert_collection_item(db, collection.id, CollectionItemData(card_variant_id=variant.id))

    assert delete_collection_item(db, collection.id, item.id) is True
    assert list_collection_items(db, collection.id) == []
    assert delete_collection_item(db, collection.id, item.id) is False


def test_upsert_collection_item_records_acquisition_fields(db):
    collection = get_or_create_default_collection(db)
    variant = _seed_variant(db)
    item = upsert_collection_item(
        db,
        collection.id,
        CollectionItemData(
            card_variant_id=variant.id,
            acquired_price=Decimal("12.34"),
            acquired_on=date(2026, 1, 1),
            storage_location="Binder 1",
            notes="pulled from a pack",
        ),
    )
    assert item.acquired_price == Decimal("12.34")
    assert item.acquired_on == date(2026, 1, 1)
    assert item.storage_location == "Binder 1"
    assert item.notes == "pulled from a pack"
