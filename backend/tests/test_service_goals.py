from datetime import date
from decimal import Decimal

import pytest
from app.models import Card, CardVariant, Collection, CollectionItem, PricePoint, Set
from app.models.enums import GoalType, Variant
from app.services.goals import (
    GoalEditError,
    GoalTypeError,
    convert_to_custom,
    create_goal,
    delete_goal,
    edit_goal_items,
    get_goal_need_list,
    mass_entry_text,
    resync_goal,
)


def _seed(db) -> tuple[Set, Card, Card, Collection]:
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", release_date=date(2024, 11, 8))
    db.add(set_row)
    db.flush()

    diglett = Card(
        ptcg_card_id="sv8-122",
        set_id=set_row.id,
        number="122",
        number_sort=122,
        name="Alolan Diglett",
        rarity="Common",
    )
    dugtrio = Card(
        ptcg_card_id="sv8-123",
        set_id=set_row.id,
        number="123",
        number_sort=123,
        name="Alolan Dugtrio",
        rarity="Uncommon",
    )
    db.add_all([diglett, dugtrio])
    db.flush()

    db.add_all(
        [
            CardVariant(
                card_id=diglett.id,
                variant=Variant.NORMAL,
                tcgplayer_product_id=589855,
                tcgplayer_sub_type_name="Normal",
                is_canonical=True,
            ),
            CardVariant(
                card_id=diglett.id,
                variant=Variant.REVERSE_HOLOFOIL,
                tcgplayer_product_id=589855,
                tcgplayer_sub_type_name="Reverse Holofoil",
                is_canonical=False,
            ),
            CardVariant(
                card_id=dugtrio.id,
                variant=Variant.NORMAL,
                tcgplayer_product_id=589856,
                tcgplayer_sub_type_name="Normal",
                is_canonical=True,
            ),
        ]
    )
    db.add_all(
        [
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=Decimal("0.06"),
            ),
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Reverse Holofoil",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=Decimal("0.19"),
            ),
            PricePoint(
                tcgplayer_product_id=589856,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=Decimal("0.06"),
            ),
        ]
    )
    collection = Collection(name="My Collection", is_default=True)
    db.add(collection)
    db.commit()
    return set_row, diglett, dugtrio, collection


def test_create_goal_set_type_materializes_canonical_variants_only(db):
    set_row, diglett, dugtrio, _collection = _seed(db)
    goal = create_goal(db, "Surging Sparks set", GoalType.SET, set_id=set_row.id)
    detail = get_goal_need_list(db, goal.id, collection_id=1)
    assert detail is not None
    assert {i.card_variant_id for i in detail.items} == {
        v.id for v in diglett.variants if v.is_canonical
    } | {v.id for v in dugtrio.variants if v.is_canonical}
    assert len(detail.items) == 2


def test_create_goal_master_set_type_materializes_all_variants(db):
    set_row, _diglett, _dugtrio, _collection = _seed(db)
    goal = create_goal(db, "Surging Sparks master set", GoalType.MASTER_SET, set_id=set_row.id)
    detail = get_goal_need_list(db, goal.id, collection_id=1)
    assert detail is not None
    assert len(detail.items) == 3  # diglett normal + reverse holo, dugtrio normal


def test_create_goal_filter_type_matches_rarity(db):
    set_row, diglett, _dugtrio, _collection = _seed(db)
    goal = create_goal(
        db,
        "All commons",
        GoalType.FILTER,
        filter_json={"set_id": set_row.id, "rarity": ["Common"]},
    )
    detail = get_goal_need_list(db, goal.id, collection_id=1)
    assert detail is not None
    assert len(detail.items) == 1
    assert detail.items[0].card_name == diglett.name


def test_need_list_excludes_fully_owned_and_computes_cost(db):
    set_row, diglett, _dugtrio, collection = _seed(db)
    normal_variant = next(v for v in diglett.variants if v.variant == Variant.NORMAL)
    db.add(
        CollectionItem(
            collection_id=collection.id,
            card_variant_id=normal_variant.id,
            quantity=1,
            condition="NM",
            language="EN",
        )
    )
    db.commit()

    goal = create_goal(db, "Surging Sparks set", GoalType.SET, set_id=set_row.id)
    detail = get_goal_need_list(db, goal.id, collection.id)
    assert detail is not None

    diglett_item = next(i for i in detail.items if i.card_variant_id == normal_variant.id)
    assert diglett_item.owned_qty == 1
    assert diglett_item.need_qty == 0

    # Only dugtrio's normal (0.06) is still needed.
    assert detail.cost.n_cards == 1
    assert detail.cost.subtotal == Decimal("0.06")


def test_need_list_empty_need_is_zero_cost(db):
    set_row, diglett, dugtrio, collection = _seed(db)
    for card in (diglett, dugtrio):
        variant = next(v for v in card.variants if v.is_canonical)
        db.add(
            CollectionItem(
                collection_id=collection.id,
                card_variant_id=variant.id,
                quantity=1,
                condition="NM",
                language="EN",
            )
        )
    db.commit()

    goal = create_goal(db, "Surging Sparks set", GoalType.SET, set_id=set_row.id)
    detail = get_goal_need_list(db, goal.id, collection.id)
    assert detail is not None
    assert detail.cost.n_cards == 0
    assert detail.cost.total == Decimal("0")


def test_resync_goal_picks_up_newly_ingested_card(db):
    set_row, _diglett, _dugtrio, collection = _seed(db)
    goal = create_goal(db, "Surging Sparks set", GoalType.SET, set_id=set_row.id)
    detail_before = get_goal_need_list(db, goal.id, collection.id)
    assert detail_before is not None
    assert len(detail_before.items) == 2

    new_card = Card(
        ptcg_card_id="sv8-124",
        set_id=set_row.id,
        number="124",
        number_sort=124,
        name="New Card",
        rarity="Rare",
    )
    db.add(new_card)
    db.flush()
    db.add(
        CardVariant(
            card_id=new_card.id,
            variant=Variant.NORMAL,
            tcgplayer_product_id=589857,
            tcgplayer_sub_type_name="Normal",
            is_canonical=True,
        )
    )
    db.commit()

    resync_goal(db, goal.id)
    detail_after = get_goal_need_list(db, goal.id, collection.id)
    assert detail_after is not None
    assert len(detail_after.items) == 3


def test_get_goal_need_list_unknown_goal_returns_none(db):
    assert get_goal_need_list(db, 999999, collection_id=1) is None


def test_delete_goal(db):
    set_row, _diglett, _dugtrio, _collection = _seed(db)
    goal = create_goal(db, "Surging Sparks set", GoalType.SET, set_id=set_row.id)
    assert delete_goal(db, goal.id) is True
    assert get_goal_need_list(db, goal.id, collection_id=1) is None
    assert delete_goal(db, goal.id) is False


def test_mass_entry_text_lists_only_still_needed_items(db):
    set_row, diglett, dugtrio, collection = _seed(db)
    goal = create_goal(db, "Surging Sparks set", GoalType.SET, set_id=set_row.id)
    owned_variant = next(v for v in diglett.variants if v.is_canonical)
    db.add(CollectionItem(collection_id=collection.id, card_variant_id=owned_variant.id, quantity=1))
    db.commit()

    detail = get_goal_need_list(db, goal.id, collection.id)
    assert detail is not None
    text = mass_entry_text(detail)

    lines = text.splitlines()
    assert len(lines) == 1  # diglett is fully owned, dugtrio is still needed
    assert lines[0] == f"1 {dugtrio.name}"
    assert text.endswith("\n")


def test_mass_entry_text_empty_when_nothing_needed(db):
    set_row, diglett, dugtrio, collection = _seed(db)
    goal = create_goal(db, "Surging Sparks set", GoalType.SET, set_id=set_row.id)
    for card in (diglett, dugtrio):
        owned_variant = next(v for v in card.variants if v.is_canonical)
        db.add(
            CollectionItem(collection_id=collection.id, card_variant_id=owned_variant.id, quantity=1)
        )
    db.commit()

    detail = get_goal_need_list(db, goal.id, collection.id)
    assert detail is not None
    assert mass_entry_text(detail) == ""


# --- custom and filter goals (catalogue fixture: see conftest.seed_catalogue) ----------------


def _item_ids(db, goal_id: int) -> set[int]:
    from app.models import GoalItem
    from sqlalchemy import select

    return set(
        db.execute(select(GoalItem.card_variant_id).where(GoalItem.goal_id == goal_id)).scalars()
    )


def test_custom_goal_holds_exactly_the_given_cards(db, catalogue):
    ids = [catalogue.pikachu_normal.id, catalogue.pikachu_ex_reverse.id]
    goal = create_goal(db, "Pikachus", GoalType.CUSTOM, card_variant_ids=ids)
    assert _item_ids(db, goal.id) == set(ids)
    # Two sets, so there is no one set to simulate sealed product for.
    assert goal.set_id is None


def test_custom_goal_within_one_set_infers_its_set(db, catalogue):
    goal = create_goal(
        db, "Sparks bits", GoalType.CUSTOM, card_variant_ids=[catalogue.ho_oh_normal.id]
    )
    assert goal.set_id == catalogue.sparks.id


def test_custom_goal_can_start_empty(db, catalogue):
    goal = create_goal(db, "Later", GoalType.CUSTOM)
    assert _item_ids(db, goal.id) == set()


def test_custom_goal_refuses_unknown_variant_ids(db, catalogue):
    with pytest.raises(GoalEditError):
        create_goal(db, "Bad", GoalType.CUSTOM, card_variant_ids=[999999])


def test_edit_goal_items_adds_and_removes(db, catalogue):
    goal = create_goal(
        db, "Edit me", GoalType.CUSTOM, card_variant_ids=[catalogue.pikachu_normal.id]
    )
    edit = edit_goal_items(
        db,
        goal.id,
        add=[catalogue.ho_oh_normal.id, catalogue.pikachu_normal.id],  # second is a repeat
        remove=[],
    )
    assert edit is not None
    assert (edit.added, edit.removed, edit.item_count) == (1, 0, 2)

    edit = edit_goal_items(db, goal.id, remove=[catalogue.pikachu_normal.id])
    assert edit is not None
    assert (edit.added, edit.removed, edit.item_count) == (0, 1, 1)
    assert _item_ids(db, goal.id) == {catalogue.ho_oh_normal.id}
    db.refresh(goal)
    assert goal.set_id == catalogue.sparks.id


def test_edit_goal_items_on_a_rule_built_goal_is_refused(db, catalogue):
    goal = create_goal(db, "Sparks", GoalType.SET, set_id=catalogue.sparks.id)
    with pytest.raises(GoalTypeError):
        edit_goal_items(db, goal.id, add=[catalogue.pikachu_normal.id])


def test_edit_goal_items_on_a_missing_goal_returns_none(db, catalogue):
    assert edit_goal_items(db, 999999, add=[]) is None


def test_resync_leaves_a_custom_goal_alone(db, catalogue):
    goal = create_goal(
        db, "Fixed", GoalType.CUSTOM, card_variant_ids=[catalogue.pikachu_normal.id]
    )
    resync_goal(db, goal.id)
    assert _item_ids(db, goal.id) == {catalogue.pikachu_normal.id}


def test_filter_goal_by_species_picks_up_new_cards_on_resync(db, catalogue):
    goal = create_goal(db, "Every Pikachu", GoalType.FILTER, filter_json={"pokedex_numbers": [25]})
    before = _item_ids(db, goal.id)
    assert before == {
        catalogue.pikachu_normal.id,
        catalogue.pikachu_ex_normal.id,
        catalogue.tag_team_holo.id,
    }

    new_card = Card(
        ptcg_card_id="sv8-300",
        set_id=catalogue.sparks.id,
        number="300",
        number_sort=300,
        name="Pikachu",
        national_pokedex_numbers=[25],
    )
    db.add(new_card)
    db.flush()
    new_variant = CardVariant(card_id=new_card.id, variant=Variant.NORMAL, is_canonical=True)
    db.add(new_variant)
    db.commit()

    resync_goal(db, goal.id)
    assert _item_ids(db, goal.id) == before | {new_variant.id}


def test_filter_goal_ignores_ownership_in_its_stored_filter(db, catalogue):
    goal = create_goal(
        db,
        "Missing Pikachus",
        GoalType.FILTER,
        filter_json={"pokedex_numbers": [25], "owned": "missing"},
    )
    # The owned Pikachu ex stays in: the need list, not membership, accounts for ownership.
    assert catalogue.pikachu_ex_normal.id in _item_ids(db, goal.id)


def test_filter_goal_with_no_filter_is_refused(db, catalogue):
    with pytest.raises(GoalEditError):
        create_goal(db, "Everything", GoalType.FILTER, filter_json={"variant_scope": "all"})


def test_filter_goal_infers_its_set_when_matches_share_one(db, catalogue):
    goal = create_goal(db, "Sparks fire", GoalType.FILTER, filter_json={
        "types": ["Fire"], "set_ids": [catalogue.sparks.id]
    })
    assert goal.set_id == catalogue.sparks.id
    every_fire = create_goal(db, "All fire", GoalType.FILTER, filter_json={"types": ["Fire"]})
    assert every_fire.set_id is None


def test_convert_to_custom_freezes_the_items_and_allows_edits(db, catalogue):
    goal = create_goal(db, "Arita", GoalType.FILTER, filter_json={"artists": ["Mitsuhiro Arita"]})
    frozen = _item_ids(db, goal.id)
    converted = convert_to_custom(db, goal.id)
    assert converted is not None and converted.goal_type == GoalType.CUSTOM
    assert _item_ids(db, goal.id) == frozen
    edit = edit_goal_items(db, goal.id, remove=[catalogue.charizard_holo.id])
    assert edit is not None and edit.item_count == len(frozen) - 1


def test_need_list_carries_set_and_image_for_multi_set_goals(db, catalogue):
    goal = create_goal(
        db,
        "Two eras",
        GoalType.CUSTOM,
        card_variant_ids=[catalogue.pikachu_ex_normal.id, catalogue.pikachu_normal.id],
    )
    detail = get_goal_need_list(db, goal.id, catalogue.collection.id)
    assert detail is not None
    # Release order, not insertion order or card number.
    assert [i.set_name for i in detail.items] == ["Base", "Surging Sparks"]
    assert detail.items[1].need_qty == 0  # the owned Pikachu ex


def _add_stamp(db, card, product_id=799999, slug="prerelease"):
    stamp = CardVariant(
        card_id=card.id,
        variant=slug,
        tcgplayer_product_id=product_id,
        tcgplayer_sub_type_name="Holofoil",
        is_canonical=False,
        is_special=True,
    )
    db.add(stamp)
    db.commit()
    return stamp


def test_master_set_excludes_stamps_and_grand_master_set_includes_them(db, catalogue):
    stamp = _add_stamp(db, catalogue.pikachu_ex)
    sparks = catalogue.sparks.id
    master = create_goal(db, "Master", GoalType.MASTER_SET, set_id=sparks)
    grand = create_goal(db, "Grand", GoalType.GRAND_MASTER_SET, set_id=sparks)
    assert stamp.id not in _item_ids(db, master.id)
    assert catalogue.pikachu_ex_reverse.id in _item_ids(db, master.id)
    assert _item_ids(db, grand.id) == _item_ids(db, master.id) | {stamp.id}


def test_need_list_labels_tagged_printings(db, catalogue):
    stamp = _add_stamp(db, catalogue.pikachu_ex, slug="worlds_2024")
    goal = create_goal(db, "Stamp", GoalType.CUSTOM, card_variant_ids=[stamp.id])
    detail = get_goal_need_list(db, goal.id, catalogue.collection.id)
    assert detail is not None
    assert detail.items[0].variant_label == "Worlds 2024 stamp"
