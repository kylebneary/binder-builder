import csv
import io
from datetime import date
from decimal import Decimal

from app.models import Card, CardVariant, PricePoint, Set
from app.models.enums import Variant
from app.services.collection import (
    CollectionItemData,
    get_or_create_default_collection,
    upsert_collection_item,
)
from app.services.csv_export import export_collection_csv


def test_export_empty_collection_is_header_only(db):
    collection = get_or_create_default_collection(db)
    content = export_collection_csv(db, collection.id)
    rows = list(csv.reader(io.StringIO(content)))
    assert len(rows) == 1  # header only


def test_export_round_trips_holding_fields(db):
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", ptcgo_code="SSP")
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
    variant = CardVariant(
        card_id=card.id,
        variant=Variant.NORMAL,
        tcgplayer_product_id=589855,
        tcgplayer_sub_type_name="Normal",
        is_canonical=True,
    )
    db.add(variant)
    db.add(
        PricePoint(
            tcgplayer_product_id=589855,
            sub_type_name="Normal",
            observed_on=date(2026, 8, 25),
            source="tcgcsv",
            market=1.23,
        )
    )
    db.commit()

    collection = get_or_create_default_collection(db)
    upsert_collection_item(
        db,
        collection.id,
        CollectionItemData(
            card_variant_id=variant.id,
            quantity=4,
            condition="LP",
            acquired_price=Decimal("0.10"),
            acquired_on=date(2026, 1, 15),
            storage_location="Binder 1",
        ),
    )

    content = export_collection_csv(db, collection.id)
    rows = list(csv.DictReader(io.StringIO(content)))
    assert len(rows) == 1
    row = rows[0]
    assert row["Set"] == "Surging Sparks"
    assert row["Set Code"] == "SSP"
    assert row["Number"] == "122"
    assert row["Name"] == "Alolan Diglett"
    assert row["Printing"] == "Normal"
    assert row["Condition"] == "LP"
    assert row["Quantity"] == "4"
    assert row["Price"] == "0.10"
    assert row["Acquired On"] == "2026-01-15"
    assert row["Storage Location"] == "Binder 1"
    assert row["Current Market Price"] == "1.23"
