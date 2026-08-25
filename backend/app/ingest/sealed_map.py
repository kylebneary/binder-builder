"""Curated sealed-product classification -- phase 1.14.

`product_type` and `packs_per_unit` can't be reliably parsed from tcgcsv product names
(docs/02-data-model.md), so unlike data/set_map.yaml (which a fuzzy matcher can seed with real
confidence from name + release date), data/sealed_map.yaml is entirely hand-curated -- there is
no auto-generator here. `bb sync sealedmap` loads it into `sealed_product` rows and reports every
tcgcsv-sealed product not yet in the file as a review-queue item, so nothing sits at the
uninformative OTHER/null defaults silently.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SealedProduct
from app.models.enums import ProductType

log = logging.getLogger(__name__)

_HEADER = (
    "# tcgplayer_product_id -> sealed product classification. Entirely hand-curated -- there is\n"
    "# no reliable way to parse product_type/packs_per_unit from tcgcsv names (see\n"
    "# docs/02-data-model.md). `bb sync sealedmap` loads this into sealed_product rows and\n"
    "# reports any tcgcsv-sealed product not yet listed here as needing classification.\n"
    "#\n"
    "# Example:\n"
    "# 565602:\n"
    "#   product_type: booster_pack\n"
    "#   packs_per_unit: 1\n"
)


@dataclass(slots=True)
class SealedMapEntry:
    product_type: ProductType
    packs_per_unit: int | None = None
    contains_promos: bool = False
    msrp: str | None = None


def load_sealed_map(path: Path) -> dict[int, SealedMapEntry]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    result: dict[int, SealedMapEntry] = {}
    for product_id, entry in data.items():
        result[int(product_id)] = SealedMapEntry(
            product_type=ProductType(entry["product_type"]),
            packs_per_unit=entry.get("packs_per_unit"),
            contains_promos=bool(entry.get("contains_promos", False)),
            msrp=entry.get("msrp"),
        )
    return result


@dataclass(slots=True)
class SealedMapSyncResult:
    tcgplayer_product_id: int
    status: str  # "updated" | "no_product_row"


def sync_sealed_map_to_db(
    db: Session, mapping: dict[int, SealedMapEntry]
) -> list[SealedMapSyncResult]:
    results: list[SealedMapSyncResult] = []
    for product_id, entry in mapping.items():
        row = db.execute(
            select(SealedProduct).where(SealedProduct.tcgplayer_product_id == product_id)
        ).scalar_one_or_none()
        if row is None:
            results.append(SealedMapSyncResult(product_id, "no_product_row"))
            continue
        row.product_type = entry.product_type
        row.packs_per_unit = entry.packs_per_unit
        row.contains_promos = entry.contains_promos
        if entry.msrp is not None:
            row.msrp = Decimal(entry.msrp)
        results.append(SealedMapSyncResult(product_id, "updated"))
    db.commit()
    return results


def unmapped_sealed_products(
    db: Session, mapping: dict[int, SealedMapEntry]
) -> list[SealedProduct]:
    """Review queue: sealed_product rows tcgcsv classified as sealed but not yet in the curated
    map -- reported, never left silently at the OTHER/null defaults."""
    all_rows = db.execute(select(SealedProduct)).scalars().all()
    return [r for r in all_rows if r.tcgplayer_product_id not in mapping]
