from decimal import Decimal

from app.ingest.sealed_map import (
    SealedMapSyncResult,
    load_sealed_map,
    sync_sealed_map_to_db,
    unmapped_sealed_products,
)
from app.models import SealedProduct
from app.models.enums import ProductType
from sqlalchemy import select


def test_load_sealed_map_missing_file_returns_empty(tmp_path):
    assert load_sealed_map(tmp_path / "does_not_exist.yaml") == {}


def test_load_sealed_map_parses_entries(tmp_path):
    path = tmp_path / "sealed_map.yaml"
    path.write_text(
        "565602:\n  product_type: booster_pack\n  packs_per_unit: 1\n"
        "565599:\n  product_type: special_collection\n  packs_per_unit: 4\n"
        "  msrp: \"29.99\"\n  contains_promos: true\n"
    )
    mapping = load_sealed_map(path)
    assert mapping[565602].product_type == ProductType.BOOSTER_PACK
    assert mapping[565602].packs_per_unit == 1
    assert mapping[565599].product_type == ProductType.SPECIAL_COLLECTION
    assert mapping[565599].contains_promos is True
    assert mapping[565599].msrp == "29.99"


def test_sync_sealed_map_updates_existing_row(db):
    db.add(SealedProduct(tcgplayer_product_id=565602, name="Sleeved Booster Pack"))
    db.commit()

    mapping = load_sealed_map_from_dict(
        {565602: {"product_type": "booster_pack", "packs_per_unit": 1}}
    )
    results = sync_sealed_map_to_db(db, mapping)
    assert results == [SealedMapSyncResult(565602, "updated")]

    row = db.execute(select(SealedProduct)).scalar_one()
    assert row.product_type == ProductType.BOOSTER_PACK
    assert row.packs_per_unit == 1


def test_sync_sealed_map_reports_missing_product_row(db):
    mapping = load_sealed_map_from_dict({999: {"product_type": "booster_pack"}})
    results = sync_sealed_map_to_db(db, mapping)
    assert results == [SealedMapSyncResult(999, "no_product_row")]


def test_sync_sealed_map_applies_msrp(db):
    db.add(SealedProduct(tcgplayer_product_id=1, name="Booster Box"))
    db.commit()
    mapping = load_sealed_map_from_dict(
        {1: {"product_type": "booster_box", "packs_per_unit": 36, "msrp": "143.64"}}
    )
    sync_sealed_map_to_db(db, mapping)
    row = db.execute(select(SealedProduct)).scalar_one()
    assert row.msrp == Decimal("143.64")


def test_unmapped_sealed_products_is_the_review_queue(db):
    db.add_all(
        [
            SealedProduct(tcgplayer_product_id=1, name="Booster Box"),
            SealedProduct(tcgplayer_product_id=2, name="Build & Battle Box"),
        ]
    )
    db.commit()
    mapping = load_sealed_map_from_dict({1: {"product_type": "booster_box"}})
    review_queue = unmapped_sealed_products(db, mapping)
    assert [p.tcgplayer_product_id for p in review_queue] == [2]


def load_sealed_map_from_dict(data: dict) -> dict:
    """Test helper: build the same dict load_sealed_map would return, without touching disk."""
    from app.ingest.sealed_map import SealedMapEntry

    return {
        product_id: SealedMapEntry(
            product_type=ProductType(entry["product_type"]),
            packs_per_unit=entry.get("packs_per_unit"),
            contains_promos=bool(entry.get("contains_promos", False)),
            msrp=entry.get("msrp"),
        )
        for product_id, entry in data.items()
    }
