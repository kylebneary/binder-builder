"""Sealed product ingest -- phase 1.14.

`ProductDTO.is_sealed` (absence of Number/Rarity in tcgcsv extendedData) reliably tells sealed
from single, but `product_type` and `packs_per_unit` "cannot be reliably parsed from names"
(docs/02-data-model.md) -- so this only upserts a bare `sealed_product` row (name,
tcgplayer_product_id, set_id when known). `product_type` defaults to OTHER and `packs_per_unit`
stays null until `data/sealed_map.yaml` is synced (see app/ingest/sealed_map.py) -- never guessed
here, since packs_per_unit is exactly the kind of number the optimizer's simulator will consume
directly later.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.base import ProductDTO
from app.models import SealedProduct, Set


def upsert_sealed_products(
    db: Session, products: list[ProductDTO], set_row: Set | None
) -> int:
    """Upsert one SealedProduct row per sealed product in `products`. Returns the count of
    newly created rows (existing rows are still refreshed, just not counted as "new")."""
    n_new = 0
    for product in products:
        if not product.is_sealed:
            continue
        row = db.execute(
            select(SealedProduct).where(
                SealedProduct.tcgplayer_product_id == product.tcgplayer_product_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = SealedProduct(tcgplayer_product_id=product.tcgplayer_product_id)
            db.add(row)
            n_new += 1
        row.name = product.name
        row.image_url = product.image_url
        if set_row is not None:
            row.set_id = set_row.id
    return n_new
