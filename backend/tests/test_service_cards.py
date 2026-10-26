from collections import Counter
from decimal import Decimal

from app.models import Goal, GoalItem
from app.models.enums import GoalType
from app.services.cards import CardQuery, card_facets, search_cards, species_name, variant_ids


def _names(result) -> list[str]:
    return [c.name for c in result.cards]


def _search(db, cat, **kw):
    sort = kw.pop("sort", "oldest")
    limit = kw.pop("limit", 60)
    offset = kw.pop("offset", 0)
    return search_cards(
        db, CardQuery(**kw), collection_id=cat.collection.id, sort=sort, limit=limit, offset=offset
    )


def test_pokedex_filter_matches_the_species_and_tag_teams_but_not_lookalike_numbers(db, catalogue):
    result = _search(db, catalogue, pokedex_numbers=[25])
    assert set(_names(result)) == {"Pikachu", "Pikachu ex", "Pikachu & Zekrom-GX"}
    # Electabuzz (125) and Ho-Oh (250) contain "25" in their JSON text and must not match.
    assert "Electabuzz" not in _names(result) and "Ho-Oh" not in _names(result)


def test_cards_without_a_variant_are_counted_not_returned(db, catalogue):
    result = _search(db, catalogue, pokedex_numbers=[25])
    assert result.total == 3
    assert result.unplaceable_count == 1  # the unpriced Pikachu ex SIR


def test_name_search_is_case_insensitive_substring(db, catalogue):
    assert set(_names(_search(db, catalogue, q="pIKa"))) == {
        "Pikachu",
        "Pikachu ex",
        "Pikachu & Zekrom-GX",
    }


def test_like_wildcards_in_the_name_are_literal(db, catalogue):
    assert _search(db, catalogue, q="%").total == 0
    assert _search(db, catalogue, q="_").total == 0


def test_type_and_subtype_lists_are_any_of(db, catalogue):
    assert set(_names(_search(db, catalogue, types=["Fire"]))) == {"Charizard", "Ho-Oh"}
    assert _names(_search(db, catalogue, subtypes=["ex"])) == ["Pikachu ex"]
    assert set(_names(_search(db, catalogue, subtypes=["ex", "Supporter"]))) == {
        "Pikachu ex",
        "Professor's Research",
    }


def test_filters_combine_with_and(db, catalogue):
    result = _search(db, catalogue, artists=["Mitsuhiro Arita"], types=["Lightning"])
    assert set(_names(result)) == {"Pikachu", "Pikachu & Zekrom-GX"}


def test_series_and_year_filters(db, catalogue):
    assert set(_names(_search(db, catalogue, series=["Base"]))) == {"Charizard", "Pikachu"}
    assert set(_names(_search(db, catalogue, year_to=2000))) == {"Charizard", "Pikachu"}
    assert "Charizard" not in _names(_search(db, catalogue, year_from=2020))


def test_variant_scope_all_lists_every_printing_under_one_card(db, catalogue):
    canonical = _search(db, catalogue, q="pikachu ex")
    every = _search(db, catalogue, q="pikachu ex", variant_scope="all")
    assert canonical.total == every.total == 1
    assert [v.variant for v in canonical.cards[0].variants] == ["normal"]
    assert {v.variant for v in every.cards[0].variants} == {"normal", "reverse_holofoil"}


def test_owned_and_missing_filters(db, catalogue):
    assert _names(_search(db, catalogue, owned="owned")) == ["Pikachu ex"]
    missing = _search(db, catalogue, owned="missing")
    assert "Pikachu ex" not in _names(missing)
    assert missing.total == 6


def test_owned_card_is_flagged(db, catalogue):
    result = _search(db, catalogue, q="pikachu ex")
    assert result.cards[0].is_owned


def test_price_bounds_and_price_sort(db, catalogue):
    result = _search(db, catalogue, min_price=Decimal("4"), max_price=Decimal("100"))
    assert set(_names(result)) == {"Pikachu", "Pikachu & Zekrom-GX"}
    by_price = _search(db, catalogue, sort="price")
    assert _names(by_price)[:2] == ["Charizard", "Pikachu & Zekrom-GX"]
    # Unpriced cards sort last rather than first.
    assert _names(by_price)[-1] == "Professor's Research"


def test_oldest_sort_runs_set_by_set_in_release_order(db, catalogue):
    names = _names(_search(db, catalogue))
    assert names[:2] == ["Charizard", "Pikachu"]


def test_pagination_reports_the_full_total(db, catalogue):
    page = _search(db, catalogue, limit=2, offset=2)
    assert page.total == 7
    assert len(page.cards) == 2


def test_goal_scope_returns_exactly_the_goal_variants(db, catalogue):
    goal = Goal(name="g", goal_type=GoalType.CUSTOM)
    db.add(goal)
    db.flush()
    db.add(GoalItem(goal_id=goal.id, card_variant_id=catalogue.pikachu_ex_reverse.id))
    db.commit()
    result = _search(db, catalogue, goal_id=goal.id)
    assert _names(result) == ["Pikachu ex"]
    # The goal's reverse holo, not the canonical normal the open search would show.
    assert [v.variant for v in result.cards[0].variants] == ["reverse_holofoil"]
    assert result.unplaceable_count == 0


def test_variant_ids_are_in_release_then_number_order(db, catalogue):
    ids = variant_ids(db, CardQuery(artists=["Mitsuhiro Arita"]))
    assert ids == [
        catalogue.charizard_holo.id, catalogue.pikachu_normal.id, catalogue.tag_team_holo.id
    ]


def test_from_dict_reads_legacy_singular_keys(catalogue):
    query = CardQuery.from_dict({"set_id": catalogue.base.id, "rarity": ["Common"], "nope": 1})
    assert query.set_ids == [catalogue.base.id]
    assert query.rarities == ["Common"]


def test_to_goal_filter_drops_ownership_and_defaults():
    query = CardQuery(artists=["A"], owned="missing", goal_id=3, min_price=Decimal("1.50"))
    assert query.to_goal_filter() == {"artists": ["A"], "min_price": "1.50"}
    assert CardQuery.from_dict(query.to_goal_filter()).min_price == Decimal("1.50")


def test_describes_anything():
    assert not CardQuery().describes_anything()
    assert not CardQuery(variant_scope="all", owned="missing").describes_anything()
    assert CardQuery(pokedex_numbers=[25]).describes_anything()


def test_facets_name_species_from_single_species_cards_only(db, catalogue):
    facets = card_facets(db)
    species = {s.pokedex_number: s for s in facets.species}
    assert species[25].name == "Pikachu"
    assert species[25].count == 4  # includes the tag team and the variant-less SIR
    # Zekrom appears only on the tag team, so it gets no name -- and no entry.
    assert 644 not in species
    assert [a.value for a in facets.artists] == ["5ban Graphics", "Mitsuhiro Arita"]
    assert {t.value for t in facets.types} == {"Fire", "Lightning"}


def test_species_name_prefers_the_shortest_then_most_common():
    assert species_name(Counter({"Pikachu ex": 5, "Pikachu": 1, "Ash's Pikachu": 2})) == "Pikachu"
