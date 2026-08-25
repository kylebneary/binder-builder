from datetime import date
from decimal import Decimal

from app.models import Card, CardVariant, CollectionItem, Set
from app.models.enums import Variant
from app.services.csv_import import apply_import, detect_columns, dry_run_import, parse_csv
from sqlalchemy import select


def _seed_sv8(db) -> Set:
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", ptcgo_code="SSP")
    db.add(set_row)
    db.flush()
    diglett = Card(
        ptcg_card_id="sv8-122",
        set_id=set_row.id,
        number="122",
        number_sort=122,
        name="Alolan Diglett",
    )
    db.add(diglett)
    db.flush()
    db.add_all(
        [
            CardVariant(card_id=diglett.id, variant=Variant.NORMAL, is_canonical=True),
            CardVariant(card_id=diglett.id, variant=Variant.REVERSE_HOLOFOIL, is_canonical=False),
        ]
    )
    db.commit()
    return set_row


COLLECTR_STYLE_CSV = (
    "Set,Card Number,Card Name,Printing,Condition,Quantity,Price Paid,Purchase Date\n"
    "Surging Sparks,122,Alolan Diglett,Normal,NM,4,0.10,2026-01-15\n"
)


def test_detect_columns_maps_common_header_variants():
    columns = detect_columns(["Set", "Card Number", "Card Name", "Printing", "Quantity"])
    assert columns == {
        "set": "Set",
        "number": "Card Number",
        "name": "Card Name",
        "printing": "Printing",
        "quantity": "Quantity",
    }


def test_parse_csv_extracts_typed_fields():
    _columns, rows = parse_csv(COLLECTR_STYLE_CSV)
    assert len(rows) == 1
    row = rows[0]
    assert row.set_name == "Surging Sparks"
    assert row.number == "122"
    assert row.quantity == 4
    assert row.price == Decimal("0.10")
    assert row.acquired_on == date(2026, 1, 15)


def test_dry_run_import_matches_without_writing(db):
    _seed_sv8(db)
    _columns, rows = parse_csv(COLLECTR_STYLE_CSV)
    results = dry_run_import(db, rows)
    assert len(results) == 1
    assert results[0].status == "matched"
    assert db.execute(select(CollectionItem)).scalars().all() == []


def test_apply_import_writes_collection_item(db):
    _seed_sv8(db)
    _columns, rows = parse_csv(COLLECTR_STYLE_CSV)
    results = apply_import(db, rows)
    assert results[0].status == "matched"
    items = db.execute(select(CollectionItem)).scalars().all()
    assert len(items) == 1
    assert items[0].quantity == 4
    assert items[0].acquired_price == Decimal("0.10")
    assert items[0].acquired_on == date(2026, 1, 15)


def test_import_unknown_set_is_reported_not_skipped(db):
    _seed_sv8(db)
    csv_text = "Set,Card Number,Card Name,Quantity\nNot A Real Set,122,Alolan Diglett,1\n"
    _columns, rows = parse_csv(csv_text)
    results = dry_run_import(db, rows)
    assert results[0].status == "no_set"
    assert "Not A Real Set" in results[0].detail


def test_import_unknown_card_number_is_reported(db):
    _seed_sv8(db)
    csv_text = "Set,Card Number,Card Name,Quantity\nSurging Sparks,999,Made Up,1\n"
    _columns, rows = parse_csv(csv_text)
    results = dry_run_import(db, rows)
    assert results[0].status == "no_card"


def test_import_reverse_holo_printing_resolves_to_correct_variant(db):
    set_row = _seed_sv8(db)
    csv_text = (
        "Set,Card Number,Card Name,Printing,Quantity\n"
        "Surging Sparks,122,Alolan Diglett,Reverse Holo,2\n"
    )
    _columns, rows = parse_csv(csv_text)
    results = apply_import(db, rows)
    assert results[0].status == "matched"
    card = db.execute(select(Card).where(Card.set_id == set_row.id)).scalar_one()
    reverse = next(v for v in card.variants if v.variant == Variant.REVERSE_HOLOFOIL)
    assert results[0].card_variant_id == reverse.id


def test_import_unrecognized_printing_falls_back_to_canonical_and_says_so(db):
    _seed_sv8(db)
    csv_text = (
        "Set,Card Number,Card Name,Printing,Quantity\n"
        "Surging Sparks,122,Alolan Diglett,Some Weird Foil,1\n"
    )
    _columns, rows = parse_csv(csv_text)
    results = dry_run_import(db, rows)
    assert results[0].status == "matched"
    assert "not recognized" in results[0].detail
