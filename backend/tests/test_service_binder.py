from datetime import date

import pytest
from app.binder.layout import AutoLayoutMode, PlacementSpec
from app.models import Binder, BinderPlacement, Card, CardVariant, Collection, CollectionItem, Set
from app.models.enums import Variant
from app.services.binder import (
    BinderData,
    LayoutError,
    PlacementBatch,
    apply_auto_layout,
    apply_batch,
    clear_placement,
    create_binder,
    delete_binder,
    export_layout_json,
    get_binder_layout,
    import_layout_json,
    move_placement,
    set_placement,
    update_binder,
)
from sqlalchemy.exc import IntegrityError


def _seed_set(db, n_cards: int = 4) -> tuple[Set, list[CardVariant]]:
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", release_date=date(2024, 11, 8))
    db.add(set_row)
    db.flush()

    rarities = ["Common", "Common", "Illustration Rare", "Uncommon"]
    variants: list[CardVariant] = []
    for i in range(1, n_cards + 1):
        card = Card(
            ptcg_card_id=f"sv8-{i:03d}",
            set_id=set_row.id,
            number=f"{i:03d}",
            number_sort=i,
            name=f"Card {i}",
            rarity=rarities[(i - 1) % len(rarities)],
            image_small=f"https://images.example/sv8/{i}.png",
        )
        db.add(card)
        db.flush()
        variant = CardVariant(
            card_id=card.id,
            variant=Variant.NORMAL,
            tcgplayer_product_id=100000 + i,
            tcgplayer_sub_type_name="Normal",
            is_canonical=True,
        )
        db.add(variant)
        variants.append(variant)
    db.flush()
    return set_row, variants


def _binder(db, **kw) -> Binder:
    return create_binder(db, BinderData(name=kw.pop("name", "Test binder"), **kw))


def test_create_and_get_layout_of_an_empty_binder(db):
    binder = _binder(db)
    layout = get_binder_layout(db, binder.id)
    assert layout is not None
    assert layout.placements == []
    assert layout.not_owned_count == 0


def test_get_layout_of_a_missing_binder_returns_none(db):
    assert get_binder_layout(db, 999) is None


def test_set_placement_joins_card_data_into_the_read_model(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))

    layout = get_binder_layout(db, binder.id)
    placed = layout.placements[0]
    assert placed.card_name == "Card 1"
    assert placed.number == "001"
    assert placed.image_small == "https://images.example/sv8/1.png"
    assert placed.variant == "normal"


def test_placements_are_flagged_not_owned_and_counted(db):
    """3.11: the roll-up lives in the read model so the CLI and the badge agree."""
    _, variants = _seed_set(db)
    collection = Collection(name="My Collection", is_default=True)
    db.add(collection)
    db.flush()
    db.add(
        CollectionItem(
            collection_id=collection.id, card_variant_id=variants[0].id, quantity=1
        )
    )
    db.flush()

    binder = _binder(db)
    apply_batch(
        db,
        binder.id,
        PlacementBatch(
            upserts=[
                PlacementSpec(0, 0, 0, card_variant_id=variants[0].id),
                PlacementSpec(0, 0, 1, card_variant_id=variants[1].id),
            ]
        ),
    )

    layout = get_binder_layout(db, binder.id)
    by_variant = {p.card_variant_id: p for p in layout.placements}
    assert by_variant[variants[0].id].is_owned is True
    assert by_variant[variants[1].id].is_owned is False
    assert layout.not_owned_count == 1


def test_a_zero_quantity_holding_does_not_count_as_owned(db):
    """A deliberate zero-of-this-variant row is not ownership -- see services/collection.py."""
    _, variants = _seed_set(db)
    collection = Collection(name="My Collection", is_default=True)
    db.add(collection)
    db.flush()
    db.add(
        CollectionItem(
            collection_id=collection.id, card_variant_id=variants[0].id, quantity=0
        )
    )
    db.flush()

    binder = _binder(db)
    set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))
    layout = get_binder_layout(db, binder.id)
    assert layout.not_owned_count == 1


# --- validation on mutation ---------------------------------------------------------------


def test_an_overlapping_batch_is_refused_and_changes_nothing(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))

    spanning = PlacementSpec(
        0, 0, 0, kind="insert", insert_asset_id=None, col_span=2
    )
    with pytest.raises(LayoutError):
        apply_batch(db, binder.id, PlacementBatch(upserts=[spanning]))

    layout = get_binder_layout(db, binder.id)
    assert len(layout.placements) == 1
    assert layout.placements[0].kind == "card"


def test_out_of_bounds_placement_is_refused(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    with pytest.raises(LayoutError):
        set_placement(db, binder.id, PlacementSpec(0, 0, 5, card_variant_id=variants[0].id))
    assert get_binder_layout(db, binder.id).placements == []


def test_gutter_spanning_insert_is_refused_in_a_top_loading_binder(db):
    binder = _binder(db, is_side_loading=False)
    spanning = PlacementSpec(
        0, 0, 2, kind="insert", insert_asset_id=None, col_span=2, spans_gutter=True
    )
    with pytest.raises(LayoutError) as exc:
        set_placement(db, binder.id, spanning)
    assert any("side-loading" in e for e in exc.value.errors)


def test_batch_on_a_missing_binder_raises_lookup_error(db):
    with pytest.raises(LookupError):
        apply_batch(db, 999, PlacementBatch())


def test_shrinking_a_binder_that_would_strand_placements_is_refused(db):
    _, variants = _seed_set(db)
    binder = _binder(db, rows=3, cols=3)
    set_placement(db, binder.id, PlacementSpec(0, 2, 2, card_variant_id=variants[0].id))

    with pytest.raises(LayoutError):
        update_binder(db, binder.id, BinderData(name="Smaller", rows=2, cols=2))

    layout = get_binder_layout(db, binder.id)
    assert (layout.rows, layout.cols) == (3, 3)
    assert len(layout.placements) == 1


# --- moves and swaps -----------------------------------------------------------------------


def test_moving_to_an_empty_pocket_leaves_the_origin_empty(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    written = set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))

    move_placement(db, binder.id, written.id, page_index=0, row=1, col=1)

    layout = get_binder_layout(db, binder.id)
    assert len(layout.placements) == 1
    assert (layout.placements[0].row, layout.placements[0].col) == (1, 1)


def test_dropping_onto_an_occupied_pocket_swaps(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    first = set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))
    set_placement(db, binder.id, PlacementSpec(0, 0, 1, card_variant_id=variants[1].id))

    move_placement(db, binder.id, first.id, page_index=0, row=0, col=1)

    layout = get_binder_layout(db, binder.id)
    at = {(p.row, p.col): p.card_variant_id for p in layout.placements}
    assert at[(0, 1)] == variants[0].id
    assert at[(0, 0)] == variants[1].id


def test_moving_across_facing_pages_is_allowed(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    written = set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))
    move_placement(db, binder.id, written.id, page_index=1, row=0, col=0)
    layout = get_binder_layout(db, binder.id)
    assert layout.placements[0].page_index == 1


def test_moving_onto_its_own_cell_is_a_no_op(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    written = set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))
    assert move_placement(db, binder.id, written.id, page_index=0, row=0, col=0) == []


def test_clearing_a_placement_removes_it(db):
    _, variants = _seed_set(db)
    binder = _binder(db)
    written = set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))
    assert clear_placement(db, binder.id, written.id) is True
    assert get_binder_layout(db, binder.id).placements == []
    assert clear_placement(db, binder.id, written.id) is False


def test_a_batch_clear_and_upsert_is_applied_atomically(db):
    """The shape undo relies on: one gesture, one call, one inverse."""
    _, variants = _seed_set(db)
    binder = _binder(db)
    set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))

    apply_batch(
        db,
        binder.id,
        PlacementBatch(
            upserts=[PlacementSpec(0, 2, 2, card_variant_id=variants[1].id)],
            clears=[(0, 0, 0)],
        ),
    )

    layout = get_binder_layout(db, binder.id)
    assert [(p.row, p.col, p.card_variant_id) for p in layout.placements] == [
        (2, 2, variants[1].id)
    ]


# --- auto-layout ----------------------------------------------------------------------------


def test_auto_layout_places_every_canonical_variant_in_number_order(db):
    set_row, _ = _seed_set(db, n_cards=4)
    binder = _binder(db)

    result = apply_auto_layout(db, binder.id, set_row.id)

    assert result.placed == 4
    assert result.unplaced == 0
    assert result.pages_used == 1
    layout = get_binder_layout(db, binder.id)
    assert [p.number for p in layout.placements] == ["001", "002", "003", "004"]


def test_auto_layout_replaces_the_previous_layout_by_default(db):
    set_row, _ = _seed_set(db)
    binder = _binder(db)
    apply_auto_layout(db, binder.id, set_row.id)
    apply_auto_layout(db, binder.id, set_row.id)
    assert len(get_binder_layout(db, binder.id).placements) == 4


def test_auto_layout_is_deterministic_across_runs(db):
    set_row, _ = _seed_set(db, n_cards=4)
    binder = _binder(db)

    apply_auto_layout(db, binder.id, set_row.id)
    first = [
        (p.page_index, p.row, p.col, p.card_variant_id)
        for p in get_binder_layout(db, binder.id).placements
    ]
    apply_auto_layout(db, binder.id, set_row.id)
    second = [
        (p.page_index, p.row, p.col, p.card_variant_id)
        for p in get_binder_layout(db, binder.id).placements
    ]
    assert first == second


def test_auto_layout_reports_cards_that_do_not_fit(db):
    set_row, _ = _seed_set(db, n_cards=4)
    binder = _binder(db, rows=1, cols=2, pages=1)
    result = apply_auto_layout(db, binder.id, set_row.id)
    assert (result.placed, result.unplaced) == (2, 2)


def test_rarity_tiered_auto_layout_breaks_pages_by_tier(db):
    set_row, _ = _seed_set(db, n_cards=4)
    binder = _binder(db)
    apply_auto_layout(db, binder.id, set_row.id, mode=AutoLayoutMode.RARITY_TIERED)

    layout = get_binder_layout(db, binder.id)
    pages = {p.rarity: p.page_index for p in layout.placements}
    assert pages["Common"] == 0
    assert pages["Uncommon"] == 1
    assert pages["Illustration Rare"] == 2


def test_auto_layout_on_a_missing_binder_raises_lookup_error(db):
    set_row, _ = _seed_set(db)
    with pytest.raises(LookupError):
        apply_auto_layout(db, 999, set_row.id)


# --- layout JSON ------------------------------------------------------------------------------


def test_layout_json_round_trips_through_a_new_binder(db):
    set_row, _ = _seed_set(db, n_cards=4)
    source = _binder(db, name="Source")
    apply_auto_layout(db, source.id, set_row.id)

    payload = export_layout_json(db, source.id)
    imported = import_layout_json(db, payload)

    original = get_binder_layout(db, source.id)
    copy = get_binder_layout(db, imported.id)
    assert imported.id != source.id
    assert copy.name == "Source"
    assert [(p.page_index, p.row, p.col, p.card_variant_id) for p in copy.placements] == [
        (p.page_index, p.row, p.col, p.card_variant_id) for p in original.placements
    ]


def test_layout_json_carries_stable_card_identity(db):
    """Local ids mean nothing in another database, so the export names the card itself."""
    set_row, _ = _seed_set(db, n_cards=1)
    binder = _binder(db)
    apply_auto_layout(db, binder.id, set_row.id)

    entry = export_layout_json(db, binder.id)["placements"][0]
    assert entry["ptcg_card_id"] == "sv8-001"
    assert entry["variant"] == "normal"


def test_import_resolves_cards_by_identity_not_by_local_id(db):
    _, variants = _seed_set(db, n_cards=1)
    payload = {
        "version": 1,
        "binder": {"name": "Ported", "rows": 3, "cols": 3, "pages": 20},
        "placements": [
            {
                "page_index": 0,
                "row": 0,
                "col": 0,
                "kind": "card",
                "card_variant_id": 99999,  # nonsense locally
                "ptcg_card_id": "sv8-001",
                "variant": "normal",
            }
        ],
    }
    imported = import_layout_json(db, payload)
    layout = get_binder_layout(db, imported.id)
    assert layout.placements[0].card_variant_id == variants[0].id


def test_import_drops_placements_for_cards_this_database_does_not_have(db):
    _seed_set(db, n_cards=1)
    payload = {
        "version": 1,
        "binder": {"name": "Ported", "rows": 3, "cols": 3, "pages": 20},
        "placements": [
            {
                "page_index": 0,
                "row": 0,
                "col": 0,
                "kind": "card",
                "card_variant_id": None,
                "ptcg_card_id": "sv1-999",
                "variant": "normal",
            }
        ],
    }
    imported = import_layout_json(db, payload)
    assert get_binder_layout(db, imported.id).placements == []


def test_import_into_an_existing_binder_replaces_its_layout(db):
    set_row, _ = _seed_set(db, n_cards=4)
    source = _binder(db, name="Source")
    apply_auto_layout(db, source.id, set_row.id)
    target = _binder(db, name="Target")
    set_placement(
        db, target.id, PlacementSpec(2, 0, 0, card_variant_id=_seed_variant_id(db, source))
    )

    import_layout_json(db, export_layout_json(db, source.id), binder_id=target.id)

    layout = get_binder_layout(db, target.id)
    assert len(layout.placements) == 4
    assert all(p.page_index == 0 for p in layout.placements)


def _seed_variant_id(db, binder: Binder) -> int:
    return get_binder_layout(db, binder.id).placements[0].card_variant_id


def test_import_rejects_an_unknown_version(db):
    with pytest.raises(ValueError, match="Unsupported layout JSON version"):
        import_layout_json(db, {"version": 99, "binder": {}, "placements": []})


def test_export_of_a_missing_binder_returns_none(db):
    assert export_layout_json(db, 999) is None


def test_the_unique_cell_index_backstops_a_duplicate_pocket(db):
    """The service layer is the real guard; this proves the DB catches a client that bypasses it."""
    _, variants = _seed_set(db)
    binder = _binder(db)
    set_placement(db, binder.id, PlacementSpec(0, 0, 0, card_variant_id=variants[0].id))

    db.add(
        BinderPlacement(
            binder_id=binder.id,
            page_index=0,
            row=0,
            col=0,
            kind="card",
            card_variant_id=variants[1].id,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_auto_layout_reports_cards_with_no_variant_at_all(db):
    """Real catalogues carry cards the price feed has never priced, so they own no
    `card_variant` row and auto-layout cannot place them. In Paldea Evolved that is all 14
    Wo-Chien / Chi-Yu / Chien-Pao / Ting-Lu ex cards -- exactly the ones worth binder space --
    so the count is reported rather than silently swallowed."""
    set_row, _ = _seed_set(db, n_cards=4)
    unpriced = Card(
        ptcg_card_id="sv8-999",
        set_id=set_row.id,
        number="999",
        number_sort=999,
        name="Never priced ex",
        rarity="Special Illustration Rare",
    )
    db.add(unpriced)
    db.flush()

    binder = _binder(db)
    result = apply_auto_layout(db, binder.id, set_row.id)

    assert result.placed == 4
    assert result.unplaced == 0
    assert result.skipped_no_variant == 1


def test_skipped_count_is_zero_when_every_card_has_a_variant(db):
    set_row, _ = _seed_set(db, n_cards=4)
    binder = _binder(db)
    assert apply_auto_layout(db, binder.id, set_row.id).skipped_no_variant == 0


def test_skipped_count_ignores_canonicality(db):
    """A card with only non-canonical variants is placeable in master mode and merely filtered
    in canonical mode -- it is not the same failure as owning no variant row at all."""
    set_row, _ = _seed_set(db, n_cards=2)
    card = Card(
        ptcg_card_id="sv8-500",
        set_id=set_row.id,
        number="500",
        number_sort=500,
        name="Reverse only",
        rarity="Common",
    )
    db.add(card)
    db.flush()
    db.add(
        CardVariant(
            card_id=card.id,
            variant=Variant.REVERSE_HOLOFOIL,
            tcgplayer_product_id=777001,
            tcgplayer_sub_type_name="Reverse Holofoil",
            is_canonical=False,
        )
    )
    db.flush()

    binder = _binder(db)
    assert apply_auto_layout(db, binder.id, set_row.id).skipped_no_variant == 0


def test_deleting_a_binder_removes_its_placements(db):
    """SQLite ignores ondelete=CASCADE unless PRAGMA foreign_keys is ON, which app/db.py now
    switches on for every connection. Without it, DELETE /binders/{id} left the placement rows
    behind pointing at a binder that no longer existed -- invisible until something counted
    rows. Postgres would have cascaded, so this also keeps the two engines behaving alike."""
    set_row, _ = _seed_set(db, n_cards=4)
    binder = _binder(db)
    apply_auto_layout(db, binder.id, set_row.id)
    assert db.query(BinderPlacement).filter_by(binder_id=binder.id).count() == 4

    assert delete_binder(db, binder.id) is True

    assert db.query(BinderPlacement).filter_by(binder_id=binder.id).count() == 0
    assert db.query(BinderPlacement).count() == 0
