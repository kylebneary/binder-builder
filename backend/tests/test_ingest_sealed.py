from app.ingest.base import ProductDTO
from app.ingest.sealed import upsert_sealed_products
from app.models import SealedProduct, Set
from sqlalchemy import select


def _sealed_product(product_id: int, name: str) -> ProductDTO:
    return ProductDTO(
        tcgplayer_product_id=product_id,
        tcgplayer_group_id=23651,
        name=name,
        clean_name=name,
        url=None,
        image_url=f"https://example.com/{product_id}.jpg",
        card_number=None,
        rarity=None,
    )


def _single(product_id: int) -> ProductDTO:
    return ProductDTO(
        tcgplayer_product_id=product_id,
        tcgplayer_group_id=23651,
        name="Some Card",
        clean_name="Some Card",
        url=None,
        image_url=None,
        card_number="1/191",
        rarity="Common",
    )


def test_upsert_sealed_products_skips_singles(db):
    n = upsert_sealed_products(db, [_single(1), _sealed_product(2, "Booster Box")], set_row=None)
    assert n == 1
    rows = db.execute(select(SealedProduct)).scalars().all()
    assert len(rows) == 1
    assert rows[0].tcgplayer_product_id == 2


def test_upsert_sealed_products_is_idempotent(db):
    products = [_sealed_product(565599, "Surging Sparks Build & Battle Box")]
    n1 = upsert_sealed_products(db, products, set_row=None)
    db.commit()
    n2 = upsert_sealed_products(db, products, set_row=None)
    db.commit()
    assert n1 == 1
    assert n2 == 0
    assert db.execute(select(SealedProduct)).scalars().all().__len__() == 1


def test_upsert_sealed_products_links_set_when_known(db):
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks")
    db.add(set_row)
    db.flush()
    upsert_sealed_products(db, [_sealed_product(565599, "Build & Battle Box")], set_row=set_row)
    row = db.execute(select(SealedProduct)).scalar_one()
    assert row.set_id == set_row.id


def test_upsert_sealed_products_null_set_id_for_unmatched_group(db):
    upsert_sealed_products(db, [_sealed_product(565599, "Build & Battle Box")], set_row=None)
    row = db.execute(select(SealedProduct)).scalar_one()
    assert row.set_id is None
