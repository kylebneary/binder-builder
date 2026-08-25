"""CSV export (roadmap 1.12): the inverse of csv_import's canonical columns, so a round-trip
export -> edit -> re-import stays sane."""
import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, CardVariant, CollectionItem, Set
from app.services.prices import get_current_prices

COLUMNS = [
    "Set",
    "Set Code",
    "Number",
    "Name",
    "Printing",
    "Condition",
    "Language",
    "Quantity",
    "Price",
    "Acquired On",
    "Grade",
    "Grader",
    "Storage Location",
    "Notes",
    "Current Market Price",
]


def export_collection_csv(db: Session, collection_id: int) -> str:
    items = list(
        db.execute(
            select(CollectionItem).where(CollectionItem.collection_id == collection_id)
        ).scalars()
    )
    if not items:
        buf = io.StringIO()
        csv.writer(buf).writerow(COLUMNS)
        return buf.getvalue()

    variant_ids = [i.card_variant_id for i in items]
    variants = {
        v.id: v
        for v in db.execute(
            select(CardVariant).where(CardVariant.id.in_(variant_ids))
        ).scalars()
    }
    card_ids = {v.card_id for v in variants.values()}
    cards = {c.id: c for c in db.execute(select(Card).where(Card.id.in_(card_ids))).scalars()}
    set_ids = {c.set_id for c in cards.values()}
    sets = {s.id: s for s in db.execute(select(Set).where(Set.id.in_(set_ids))).scalars()}
    product_ids = sorted(
        {v.tcgplayer_product_id for v in variants.values() if v.tcgplayer_product_id}
    )
    prices = get_current_prices(db, product_ids)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for item in items:
        variant = variants.get(item.card_variant_id)
        card = cards.get(variant.card_id) if variant else None
        set_row = sets.get(card.set_id) if card else None
        price = None
        if variant and variant.tcgplayer_product_id and variant.tcgplayer_sub_type_name:
            price = prices.get((variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name))
        writer.writerow(
            [
                set_row.name if set_row else "",
                set_row.ptcgo_code if set_row else "",
                card.number if card else "",
                card.name if card else "",
                variant.tcgplayer_sub_type_name if variant else "",
                item.condition,
                item.language,
                item.quantity,
                item.acquired_price if item.acquired_price is not None else "",
                item.acquired_on.isoformat() if item.acquired_on else "",
                item.grade or "",
                item.grader or "",
                item.storage_location or "",
                item.notes or "",
                price["market"] if price and price["market"] is not None else "",
            ]
        )
    return buf.getvalue()
