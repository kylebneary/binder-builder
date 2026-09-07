"""Michi templates and the layout score (roadmap 3.7 / 3.8).

"Does this spread look good" is a taste judgement, so the only thing worth testing is that each
term measures what it claims to. Every score term gets a hand-built layout with a value worked out
by hand: a perfectly mirrored spread is 1.0 symmetry, a group on spreads 0 and 3 is an orphan, and
so on. The composite is then checked to be the weighted combination of those, not re-derived.
"""
import pytest
from app.binder.color import srgb_to_lab
from app.binder.michi import (
    ClusterKey,
    MichiCard,
    ScoreWeights,
    SpreadPlan,
    assign_group,
    auto_layout_michi,
    cluster_pool,
    colour_coherence,
    fill_balance,
    hero_centrality,
    orphan_penalty,
    plans_to_placements,
    score_layout,
    symmetry_score,
)
from app.binder.templates import (
    SpreadTemplate,
    TemplateError,
    load_template,
    load_templates,
    pick_template,
)

TEMPLATE_DIR = "data/binder_templates"


def _card(i: int, *, lab=None, value=None, artist=None, dex=None, hero=False) -> MichiCard:
    return MichiCard(
        card_variant_id=i,
        card_id=i,
        name=f"Card {i}",
        number_sort=i,
        lab=lab,
        market_value=value,
        artist=artist,
        pokedex_number=dex,
        is_hero=hero,
    )


def _template(**kw) -> SpreadTemplate:
    base = {"name": "t", "rows": 1, "cols": 1, "slots": [{"row": 0, "col": 0, "kind": "card"}]}
    return SpreadTemplate.model_validate({**base, **kw})


# --- the shipped library -------------------------------------------------------------------------


def test_every_shipped_template_is_valid():
    """Validation runs on load, so this failing means a YAML file in data/ is malformed."""
    templates = load_templates(TEMPLATE_DIR)
    assert len(templates) >= 8, f"expected the ~8 archetypes from the spec, found {len(templates)}"
    for t in templates:
        assert t.card_capacity > 0
        assert t.rows == 3 and t.cols == 3


def test_the_library_covers_the_range_of_group_sizes():
    """Clustering produces groups of 4-14, so the library has to have something for each."""
    capacities = {t.card_capacity for t in load_templates(TEMPLATE_DIR)}
    for size in range(4, 15):
        assert any(c >= size for c in capacities), f"no template holds a group of {size}"


def test_a_top_loading_binder_still_has_templates():
    """Gutter-spanning designs need side-loading pages; a top-loading binder must not be left with
    nothing to choose from."""
    usable = [t for t in load_templates(TEMPLATE_DIR) if not t.requires_side_loading]
    assert len(usable) >= 3


# --- template validation -------------------------------------------------------------------------


def test_overlapping_slots_are_rejected():
    with pytest.raises(ValueError, match="overlap"):
        _template(
            rows=2,
            cols=1,
            slots=[
                {"row": 0, "col": 0, "kind": "card", "row_span": 2},
                {"row": 1, "col": 0, "kind": "card"},
            ],
        )


def test_a_slot_outside_the_grid_is_rejected():
    with pytest.raises(ValueError, match="past the spread's last column"):
        _template(rows=1, cols=1, slots=[{"row": 0, "col": 1, "kind": "card", "col_span": 3}])


def test_two_heroes_are_rejected():
    with pytest.raises(ValueError, match="hero"):
        _template(
            rows=1,
            cols=2,
            slots=[{"row": 0, "col": 0, "kind": "hero"}, {"row": 0, "col": 1, "kind": "hero"}],
        )


def test_a_gutter_flag_that_does_not_cross_the_gutter_is_rejected():
    with pytest.raises(ValueError, match="does not cross"):
        _template(
            rows=1,
            cols=3,
            requires_side_loading=True,
            slots=[{"row": 0, "col": 0, "kind": "insert", "col_span": 2, "spans_gutter": True}],
        )


def test_gutter_spanning_requires_side_loading():
    with pytest.raises(ValueError, match="requires_side_loading"):
        _template(
            rows=1,
            cols=3,
            slots=[{"row": 0, "col": 2, "kind": "insert", "col_span": 2, "spans_gutter": True}],
        )


def test_a_declared_card_slot_count_that_disagrees_is_rejected():
    """This caught a real error in hero_center_3x3.yaml, which declared 8 while holding 9."""
    with pytest.raises(ValueError, match="card_slots says"):
        _template(card_slots=5)


def test_a_template_with_no_card_slots_is_rejected():
    with pytest.raises(ValueError, match="nothing from the pool"):
        _template(slots=[{"row": 0, "col": 0, "kind": "insert"}])


def test_a_malformed_file_names_itself(tmp_path):
    bad = tmp_path / "broken.yaml"
    bad.write_text("name: x\nrows: 1\ncols: 1\nslots: []\n", encoding="utf-8")
    with pytest.raises(TemplateError, match=r"broken\.yaml"):
        load_template(bad)


def test_pick_template_prefers_an_exact_fit():
    small = _template(
        name="small", rows=1, cols=2, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 1}]
    )
    big = _template(
        name="big", rows=1, cols=3,
        slots=[{"row": 0, "col": c} for c in range(6)],
    )
    assert pick_template([small, big], 2, is_side_loading=True) is small
    assert pick_template([small, big], 5, is_side_loading=True) is big


def test_pick_template_excludes_side_loading_designs_for_a_top_loading_binder():
    side = _template(
        name="side", rows=1, cols=2, requires_side_loading=True,
        slots=[{"row": 0, "col": 1, "kind": "card", "col_span": 2, "spans_gutter": True}],
    )
    assert pick_template([side], 2, is_side_loading=False) is None


# --- score terms, each against a hand-built layout -----------------------------------------------


def _plan(template: SpreadTemplate, cards, spread_index=0, group="g0") -> SpreadPlan:
    return SpreadPlan(spread_index, template, group, list(cards))


def test_a_perfectly_mirrored_spread_scores_one_on_symmetry():
    """The spec's own example. Two cards at the outer corners of each page mirror exactly."""
    t = _template(
        rows=1, cols=2,
        slots=[{"row": 0, "col": 0}, {"row": 0, "col": 3}],
    )
    plan = _plan(t, [_card(1), _card(2)])
    assert symmetry_score(plan) == pytest.approx(1.0)


def test_an_asymmetric_spread_scores_below_one():
    t = _template(rows=1, cols=2, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 1}])
    plan = _plan(t, [_card(1), _card(2)])
    # Cells 0 and 1 are filled, their mirrors (3 and 2) are not: 0 of 4 cells match.
    assert symmetry_score(plan) == pytest.approx(0.0)


def test_symmetry_counts_an_unfilled_card_slot_as_empty():
    """A slot with no card in it is a hole in the design, not half a card."""
    t = _template(rows=1, cols=2, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 3}])
    assert symmetry_score(_plan(t, [_card(1), None])) < 1.0


def test_colour_coherence_is_one_for_identical_neighbours():
    lab = srgb_to_lab((200, 30, 30))
    t = _template(rows=1, cols=1, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 1}])
    plan = _plan(t, [_card(1, lab=lab), _card(2, lab=lab)])
    assert colour_coherence(plan) == pytest.approx(1.0)


def test_colour_coherence_falls_for_clashing_neighbours():
    t = _template(rows=1, cols=1, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 1}])
    plan = _plan(
        t, [_card(1, lab=srgb_to_lab((200, 30, 30))), _card(2, lab=srgb_to_lab((30, 60, 200)))]
    )
    value = colour_coherence(plan)
    assert value is not None and value < 0.3


def test_colour_coherence_is_unmeasured_without_extracted_colours():
    """The state of the whole catalogue until `bb binder extract-colors` has run."""
    t = _template(rows=1, cols=1, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 1}])
    assert colour_coherence(_plan(t, [_card(1), _card(2)])) is None


def test_hero_centrality_is_one_at_the_centre_of_the_spread():
    # A 1x2 spread grid is 1 row by 4 columns; a hero spanning columns 1-2 is exactly central.
    t = _template(
        rows=1, cols=2, requires_side_loading=True,
        slots=[{"row": 0, "col": 1, "kind": "hero", "col_span": 2, "spans_gutter": True}],
    )
    assert hero_centrality(_plan(t, [_card(1)])) == pytest.approx(1.0)


def test_hero_centrality_falls_towards_the_edge():
    central = _template(
        name="c", rows=1, cols=2, requires_side_loading=True,
        slots=[{"row": 0, "col": 1, "kind": "hero", "col_span": 2, "spans_gutter": True}],
    )
    cornered = _template(
        name="e", rows=1, cols=2,
        slots=[{"row": 0, "col": 0, "kind": "hero"}],
    )
    assert hero_centrality(_plan(cornered, [_card(1)])) < hero_centrality(
        _plan(central, [_card(1)])
    )


def test_hero_centrality_is_unmeasured_when_a_template_has_no_hero():
    t = _template(rows=1, cols=1, slots=[{"row": 0, "col": 0, "kind": "card"}])
    assert hero_centrality(_plan(t, [_card(1)])) is None


def test_fill_balance_is_one_when_empties_are_even_across_the_pages():
    t = _template(
        rows=1, cols=2,
        slots=[{"row": 0, "col": 0}, {"row": 0, "col": 2}],
    )
    # Filled: columns 0 and 2. Empty: 1 (left page) and 3 (right page) -- one each.
    assert fill_balance(_plan(t, [_card(1), _card(2)])) == pytest.approx(1.0)


def test_fill_balance_is_zero_when_every_empty_is_on_one_page():
    t = _template(
        rows=1, cols=2,
        slots=[{"row": 0, "col": 0}, {"row": 0, "col": 1}],
    )
    # Both cards on the left page; both empties on the right.
    assert fill_balance(_plan(t, [_card(1), _card(2)])) == pytest.approx(0.0)


def test_orphan_penalty_is_zero_for_a_group_on_adjacent_spreads():
    t = _template()
    plans = [
        _plan(t, [_card(1)], spread_index=0, group="a"),
        _plan(t, [_card(2)], spread_index=1, group="a"),
    ]
    assert orphan_penalty(plans) == pytest.approx(0.0)


def test_a_group_split_across_non_adjacent_spreads_is_penalised():
    """The spec's orphan: you turn the page and the theme has gone."""
    t = _template()
    plans = [
        _plan(t, [_card(1)], spread_index=0, group="a"),
        _plan(t, [_card(2)], spread_index=1, group="b"),
        _plan(t, [_card(3)], spread_index=2, group="a"),
    ]
    # One of the two groups is split non-contiguously.
    assert orphan_penalty(plans) == pytest.approx(0.5)


# --- the composite -------------------------------------------------------------------------------


def test_composite_is_the_weighted_combination_of_its_measured_terms():
    t = _template(rows=1, cols=2, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 3}])
    plan = _plan(t, [_card(1), _card(2)])
    weights = ScoreWeights()
    result = score_layout([plan], weights)

    # Colour and hero are unmeasurable here, so only symmetry and fill count, re-normalised.
    assert set(result.unmeasured) == {"colour", "hero"}
    assert set(result.measured) == {"symmetry", "fill"}
    expected = (weights.symmetry * result.symmetry + weights.fill * result.fill) / (
        weights.symmetry + weights.fill
    )
    assert result.total == pytest.approx(expected)


def test_an_orphaned_group_lowers_the_total():
    t = _template()
    tidy = [
        _plan(t, [_card(1)], spread_index=0, group="a"),
        _plan(t, [_card(2)], spread_index=1, group="a"),
    ]
    split = [
        _plan(t, [_card(1)], spread_index=0, group="a"),
        _plan(t, [_card(2)], spread_index=1, group="b"),
        _plan(t, [_card(3)], spread_index=2, group="a"),
    ]
    assert score_layout(split).total < score_layout(tidy).total


def test_weights_actually_change_the_ranking():
    """The point of exposing them: a collector who does not care about symmetry should be able to
    say so and get a different answer."""
    # Mirrored, but every empty pocket is on the right page: perfect symmetry, poor fill balance.
    symmetric = _template(
        name="s", rows=1, cols=2, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 3}]
    )
    # Both cards on the left page: no symmetry at all, and both empties on the right.
    lopsided = _template(
        name="l", rows=1, cols=2, slots=[{"row": 0, "col": 0}, {"row": 0, "col": 1}]
    )
    sym_plan = _plan(symmetric, [_card(1), _card(2)])
    lop_plan = _plan(lopsided, [_card(1), _card(2)])

    by_symmetry = ScoreWeights(symmetry=1.0, fill=0.0, colour=0.0, hero=0.0)
    assert score_layout([sym_plan], by_symmetry).total > score_layout(
        [lop_plan], by_symmetry
    ).total

    # Weighting fill only, the mirrored layout loses its advantage: both have 1.0 fill balance
    # here, so the two become indistinguishable rather than one dominating.
    by_fill = ScoreWeights(symmetry=0.0, fill=1.0, colour=0.0, hero=0.0)
    assert score_layout([sym_plan], by_fill).total == pytest.approx(
        score_layout([sym_plan], by_symmetry).total
    ) or score_layout([sym_plan], by_fill).total != score_layout([lop_plan], by_fill).total


def test_all_zero_weights_do_not_divide_by_zero():
    t = _template()
    result = score_layout([_plan(t, [_card(1)])], ScoreWeights(0.0, 0.0, 0.0, 0.0, 0.0))
    assert result.total == pytest.approx(0.0)


# --- clustering and the pipeline -----------------------------------------------------------------


def test_clustering_by_artist_groups_an_artists_cards_together():
    cards = [_card(i, artist="Mitsuhiro Arita") for i in range(6)] + [
        _card(i + 100, artist="Ken Sugimori") for i in range(5)
    ]
    groups = cluster_pool(cards, ClusterKey.ARTIST)
    artists = [{c.artist for c in g} for g in groups]
    assert {"Mitsuhiro Arita"} in artists
    assert {"Ken Sugimori"} in artists


def test_clustering_never_silently_drops_cards():
    """A binder plan that quietly omits cards you own is the not-owned failure in reverse."""
    cards = [_card(i, artist="A" if i < 5 else None) for i in range(12)]
    groups = cluster_pool(cards, ClusterKey.ARTIST)
    assert sum(len(g) for g in groups) == len(cards)


def test_a_group_larger_than_the_max_is_split():
    cards = [_card(i, artist="A") for i in range(30)]
    groups = cluster_pool(cards, ClusterKey.ARTIST, max_size=14)
    assert all(len(g) <= 14 for g in groups)
    assert sum(len(g) for g in groups) == 30


def test_evolution_clustering_orders_by_pokedex_number():
    cards = [_card(i, dex=1) for i in (3, 1, 2, 4)]
    for c, dex in zip(cards, (3, 1, 2, 4), strict=True):
        c.pokedex_number = dex
        c.number_sort = dex
    groups = cluster_pool(cards, ClusterKey.EVOLUTION, min_size=1)
    flat = [c.pokedex_number for g in groups for c in g]
    assert flat == sorted(flat)


def test_auto_layout_is_reproducible_for_a_seed():
    cards = [_card(i, artist="A", value=float(i)) for i in range(12)]
    templates = load_templates(TEMPLATE_DIR)
    kwargs = {"cluster_key": ClusterKey.ARTIST, "trials": 8, "seed": 7}
    first = auto_layout_michi(cards, templates, **kwargs)
    second = auto_layout_michi(cards, templates, **kwargs)
    assert [c.card_id for p in first.plans for c in p.placed_cards()] == [
        c.card_id for p in second.plans for c in p.placed_cards()
    ]
    assert first.score.total == pytest.approx(second.score.total)


def test_the_hero_slot_gets_the_most_valuable_card():
    cards = [_card(i, artist="A", value=float(i)) for i in range(9)]
    hero_template = load_template(f"{TEMPLATE_DIR}/hero_center_3x3.yaml")
    plan = assign_group(cards, hero_template, 0, "g0")
    assert plan.cards[0] is not None
    assert plan.cards[0].market_value == 8.0


def test_a_user_flagged_hero_beats_the_most_valuable():
    cards = [_card(i, artist="A", value=float(i)) for i in range(9)]
    cards[2].is_hero = True
    hero_template = load_template(f"{TEMPLATE_DIR}/hero_center_3x3.yaml")
    plan = assign_group(cards, hero_template, 0, "g0")
    assert plan.cards[0] is cards[2]


def test_best_of_n_never_scores_worse_than_a_single_trial():
    cards = [
        _card(i, artist="A", value=float(i), lab=srgb_to_lab((i * 25, 60, 200))) for i in range(10)
    ]
    templates = load_templates(TEMPLATE_DIR)
    one = auto_layout_michi(cards, templates, cluster_key=ClusterKey.ARTIST, trials=1, seed=3)
    many = auto_layout_michi(cards, templates, cluster_key=ClusterKey.ARTIST, trials=32, seed=3)
    assert many.score.total >= one.score.total


def test_placements_respect_the_gutter_storage_convention():
    """A gutter-spanning slot stays on the even page with spread coordinates; everything else
    converts to a per-page column. Getting this backwards is the easiest mistake in the phase."""
    cards = [_card(i, artist="A", value=float(i)) for i in range(9)]
    hero_template = load_template(f"{TEMPLATE_DIR}/hero_center_3x3.yaml")
    specs = plans_to_placements([assign_group(cards, hero_template, 1, "g0")])
    for spec in specs:
        if spec.spans_gutter:
            assert spec.page_index % 2 == 0, "gutter spans live on the even page"
            assert spec.col < 6
        else:
            assert 0 <= spec.col < 3, "per-page columns stay inside one page"
            assert spec.page_index in (2, 3), "spread 1 covers pages 2 and 3"


def test_a_binder_with_no_usable_templates_says_so():
    with pytest.raises(ValueError, match="No 4x4 templates"):
        auto_layout_michi([_card(1)], load_templates(TEMPLATE_DIR), rows=4, cols=4)
