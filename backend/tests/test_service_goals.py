from datetime import date
from decimal import Decimal

from app.models import Card, CardVariant, Collection, CollectionItem, PricePoint, Set
from app.models.enums import GoalType, Variant
from app.services.goals import (
    create_goal,
    delete_goal,
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
