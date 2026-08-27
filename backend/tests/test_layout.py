from app.binder.layout import (
    RARITY_ORDER,
    AutoLayoutMode,
    Geometry,
    LayoutCard,
    PlacementSpec,
    Rect,
    _rarity_rank,
    auto_layout,
    spread_of,
    to_spread_rect,
    validate_page,
    validate_placements,
)


def card(page, row, col, variant_id=1, **kw):
    return PlacementSpec(page, row, col, kind="card", card_variant_id=variant_id, **kw)


def insert(page, row, col, asset_id=1, **kw):
    return PlacementSpec(page, row, col, kind="insert", insert_asset_id=asset_id, **kw)


def test_non_overlapping_rects_are_valid():
    rects = [Rect(0, 0), Rect(0, 1, col_span=2), Rect(1, 0, row_span=2, col_span=3)]
    assert validate_page(rects, rows=3, cols=3) == []


def test_overlap_is_detected():
    rects = [Rect(0, 0, col_span=2), Rect(0, 1)]
    errors = validate_page(rects, rows=3, cols=3)
    assert any("overlap" in e for e in errors)


def test_out_of_bounds_is_detected():
    errors = validate_page([Rect(2, 2, row_span=2)], rows=3, cols=3)
    assert any("does not fit" in e for e in errors)


# --- spread geometry ---------------------------------------------------------------------


def test_pages_pair_into_spreads():
    assert spread_of(0) == spread_of(1) == 0
    assert spread_of(2) == spread_of(3) == 1


def test_right_page_placements_shift_into_the_second_half_of_the_spread():
    left = to_spread_rect(card(0, 0, 0), cols=3)
    right = to_spread_rect(card(1, 0, 0), cols=3)
    assert left.col == 0
    assert right.col == 3
    assert not left.overlaps(right)


def test_facing_pages_at_the_same_pocket_do_not_collide():
    assert validate_placements([card(0, 1, 2), card(1, 1, 2)], Geometry()) == []


def test_gutter_spanning_insert_collides_with_the_facing_page():
    spanning = insert(0, 0, 2, col_span=2, spans_gutter=True)
    facing = card(1, 0, 0)  # spread column 3, which the insert covers
    errors = validate_placements([spanning, facing], Geometry())
    assert any("overlap" in e for e in errors)


def test_gutter_spanning_insert_clears_a_facing_card_it_does_not_reach():
    spanning = insert(0, 0, 2, col_span=2, spans_gutter=True)
    facing = card(1, 0, 1)  # spread column 4
    assert validate_placements([spanning, facing], Geometry()) == []


# --- the invariants the service layer needs ----------------------------------------------


def test_gutter_spanning_is_refused_in_a_top_loading_binder():
    spanning = insert(0, 0, 2, col_span=2, spans_gutter=True)
    errors = validate_placements([spanning], Geometry(is_side_loading=False))
    assert any("side-loading" in e for e in errors)


def test_gutter_flag_without_actually_crossing_the_gutter_is_refused():
    not_spanning = insert(0, 0, 0, col_span=2, spans_gutter=True)
    errors = validate_placements([not_spanning], Geometry())
    assert any("does not cross the gutter" in e for e in errors)


def test_gutter_spanning_must_sit_on_the_even_page():
    spanning = insert(1, 0, 2, col_span=2, spans_gutter=True)
    errors = validate_placements([spanning], Geometry())
    assert any("even (left) page" in e for e in errors)


def test_gutter_spanning_may_use_the_full_spread_width():
    spanning = insert(0, 0, 0, col_span=6, spans_gutter=True)
    assert validate_placements([spanning], Geometry()) == []


def test_card_kind_requires_a_card_variant():
    errors = validate_placements([PlacementSpec(0, 0, 0, kind="card")], Geometry())
    assert any("no card_variant_id" in e for e in errors)


def test_insert_kind_requires_an_insert_asset():
    errors = validate_placements([PlacementSpec(0, 0, 0, kind="insert")], Geometry())
    assert any("no insert_asset_id" in e for e in errors)


def test_empty_kind_must_not_reference_anything():
    errors = validate_placements(
        [PlacementSpec(0, 0, 0, kind="empty", card_variant_id=7)], Geometry()
    )
    assert any("still references" in e for e in errors)


def test_placement_beyond_the_last_page_is_refused():
    errors = validate_placements([card(20, 0, 0)], Geometry(pages=20))
    assert any("outside the 20 pages" in e for e in errors)


def test_non_spanning_placement_is_bounded_by_the_page_not_the_spread():
    """col 3 is a legal spread column but not a legal page column -- catching this is the
    whole reason the two coordinate spaces are kept distinct."""
    errors = validate_placements([card(0, 0, 3)], Geometry())
    assert any("does not fit in the 3x3 grid" in e for e in errors)


# --- auto-layout -------------------------------------------------------------------------


def pool():
    return [
        LayoutCard(1, number="003", number_sort=3, rarity="Rare"),
        LayoutCard(2, number="001", number_sort=1, rarity="Common"),
        LayoutCard(3, number="002", number_sort=2, rarity="Common"),
    ]


def test_set_order_fills_in_number_order_left_to_right():
    placements = auto_layout(pool(), Geometry())
    assert [p.card_variant_id for p in placements] == [2, 3, 1]
    assert [(p.page_index, p.row, p.col) for p in placements] == [(0, 0, 0), (0, 0, 1), (0, 0, 2)]


def test_set_order_wraps_rows_then_pages():
    cards = [LayoutCard(i, number=f"{i:03d}", number_sort=i) for i in range(1, 12)]
    placements = auto_layout(cards, Geometry(rows=3, cols=3))
    assert (placements[3].row, placements[3].col) == (1, 0)
    assert placements[8].page_index == 0
    assert (placements[9].page_index, placements[9].row, placements[9].col) == (1, 0, 0)


def test_auto_layout_output_is_always_valid():
    cards = [LayoutCard(i, number=f"{i:03d}", number_sort=i) for i in range(1, 40)]
    geometry = Geometry()
    assert validate_placements(auto_layout(cards, geometry), geometry) == []


def test_auto_layout_is_deterministic():
    cards = [LayoutCard(i, number=f"{i:03d}", number_sort=i % 5) for i in range(1, 20)]
    first = auto_layout(cards, Geometry())
    second = auto_layout(list(reversed(cards)), Geometry())
    assert [(p.page_index, p.row, p.col, p.card_variant_id) for p in first] == [
        (p.page_index, p.row, p.col, p.card_variant_id) for p in second
    ]


def test_skip_reverse_holos_drops_them():
    cards = [*pool(), LayoutCard(4, number="004", number_sort=4, variant="reverse_holofoil")]
    placements = auto_layout(cards, Geometry(), skip_reverse_holos=True)
    assert 4 not in [p.card_variant_id for p in placements]


def test_rarity_tiered_puts_each_tier_on_its_own_page_with_chases_last():
    cards = [
        LayoutCard(1, number="001", number_sort=1, rarity="Common"),
        LayoutCard(2, number="002", number_sort=2, rarity="Common"),
        LayoutCard(3, number="003", number_sort=3, rarity="Illustration Rare"),
    ]
    placements = auto_layout(cards, Geometry(), mode=AutoLayoutMode.RARITY_TIERED)
    by_variant = {p.card_variant_id: p for p in placements}
    assert by_variant[1].page_index == by_variant[2].page_index == 0
    assert by_variant[3].page_index == 1


def test_unknown_rarities_sort_after_known_ones():
    cards = [
        LayoutCard(1, number="001", number_sort=1, rarity="Some New Rarity"),
        LayoutCard(2, number="002", number_sort=2, rarity="Hyper Rare"),
    ]
    placements = auto_layout(cards, Geometry(), mode=AutoLayoutMode.RARITY_TIERED)
    assert [p.card_variant_id for p in placements] == [2, 1]


def test_subsets_start_on_a_new_page():
    cards = [
        LayoutCard(1, number="001", number_sort=1),
        LayoutCard(2, number="TG01", number_sort=2),
    ]
    placements = auto_layout(cards, Geometry(), start_subset_on_new_page=True)
    assert placements[0].page_index == 0
    assert placements[1].page_index == 1


def test_cards_beyond_the_last_page_are_dropped():
    cards = [LayoutCard(i, number=f"{i:03d}", number_sort=i) for i in range(1, 30)]
    placements = auto_layout(cards, Geometry(rows=3, cols=3, pages=2))
    assert len(placements) == 18


# The 38 distinct `card.rarity` values in the ingested catalogue (20,479 cards, 174 sets) as of
# 2026-08-27. Pinned here because the real data is gitignored and cannot be reached from a test:
# without this list, dropping a rarity from RARITY_ORDER would silently demote a sixth of the
# catalogue to the alphabetical fallback and nothing would fail.
OBSERVED_RARITIES = (
    "ACE SPEC Rare",
    "Amazing Rare",
    "Black White Rare",
    "Classic Collection",
    "Common",
    "Double Rare",
    "Hyper Rare",
    "Illustration Rare",
    "LEGEND",
    "MEGA_ATTACK_RARE",
    "Mega Hyper Rare",
    "Promo",
    "Radiant Rare",
    "Rare",
    "Rare ACE",
    "Rare BREAK",
    "Rare Holo",
    "Rare Holo EX",
    "Rare Holo GX",
    "Rare Holo LV.X",
    "Rare Holo Star",
    "Rare Holo V",
    "Rare Holo VMAX",
    "Rare Holo VSTAR",
    "Rare Prime",
    "Rare Prism Star",
    "Rare Rainbow",
    "Rare Secret",
    "Rare Shining",
    "Rare Shiny",
    "Rare Shiny GX",
    "Rare Ultra",
    "Shiny Rare",
    "Shiny Ultra Rare",
    "Special Illustration Rare",
    "Trainer Gallery Rare Holo",
    "Ultra Rare",
    "Uncommon",
)


def test_every_known_rarity_string_is_ordered():
    missing = [r for r in OBSERVED_RARITIES if r not in RARITY_ORDER]
    assert missing == [], f"unordered rarities fall back to alphabetical sorting: {missing}"


def test_rarity_order_has_no_duplicates():
    assert len(RARITY_ORDER) == len(set(RARITY_ORDER))


def test_promos_sort_into_the_bulk_tier_not_the_chase_tier():
    """Promos are mass-distributed. The alphabetical fallback used to rank them above Hyper
    Rare, which put a stack of energy promos in the chase pages."""
    assert _rarity_rank("Promo") < _rarity_rank("Rare")
    assert _rarity_rank("Promo") < _rarity_rank("Hyper Rare")


def test_old_era_ultras_outrank_plain_holos():
    for ultra in ("Rare Holo EX", "Rare Holo GX", "Rare Holo LV.X", "Rare Ultra"):
        assert _rarity_rank(ultra) > _rarity_rank("Rare Holo")


def test_an_unmapped_rarity_still_sorts_last():
    assert _rarity_rank("Some Future Rarity") > _rarity_rank("Rare Holo Star")
    assert _rarity_rank(None) > _rarity_rank("Some Future Rarity")
