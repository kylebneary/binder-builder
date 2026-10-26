"""Placeholder `unpriced` printings: created for cards the price feed hasn't priced, so they can go
in goals and binders, and retired -- references moved -- once a real printing is derived."""
from datetime import date

from app.ingest.base import PricePointDTO, ProductDTO
from app.ingest.placeholders import ensure_placeholders, retire_placeholders
from app.ingest.prices import _derive_variants
from app.models import (
    Binder,
    BinderPlacement,
    Card,
    CardVariant,
    Collection,
    CollectionItem,
    Goal,
    GoalItem,
    Set,
)
from app.models.enums import GoalType, PlacementKind
from app.services.goals import create_goal
from sqlalchemy import select


def _set_with_cards(db, *numbers: str) -> tuple[Set, list[Card]]:
    set_row = Set(ptcg_set_id="base1", name="Base")
    db.add(set_row)
    db.flush()
    cards = [
        Card(ptcg_card_id=f"base1-{n}", set_id=set_row.id, number=n, name=f"Card {n}")
        for n in numbers
    ]
    db.add_all(cards)
    db.flush()
    return set_row, cards


def _variants(db, card: Card) -> dict[str, CardVariant]:
    rows = db.execute(select(CardVariant).where(CardVariant.card_id == card.id)).scalars()
    return {str(r.variant): r for r in rows}


def test_ensure_placeholders_covers_only_cards_with_no_printing(db):
    set_row, (priced, unpriced) = _set_with_cards(db, "1", "2")
    db.add(CardVariant(card_id=priced.id, variant="holofoil", is_canonical=True))
    db.flush()

    assert ensure_placeholders(db, set_row.id) == 1
    assert ensure_placeholders(db, set_row.id) == 0  # idempotent
    db.commit()
    assert set(_variants(db, priced)) == {"holofoil"}
    placeholder = _variants(db, unpriced)["unpriced"]
    assert placeholder.is_canonical and not placeholder.is_special
    assert placeholder.tcgplayer_product_id is None


def test_a_placeholder_lets_the_card_into_a_set_goal(db):
    set_row, (card,) = _set_with_cards(db, "1")
    ensure_placeholders(db, set_row.id)
    db.commit()
    goal = create_goal(db, "Base", GoalType.SET, set_id=set_row.id)
    items = db.execute(select(GoalItem).where(GoalItem.goal_id == goal.id)).scalars().all()
    assert [i.card_variant_id for i in items] == [_variants(db, card)["unpriced"].id]


def test_price_ingest_retires_the_placeholder_and_moves_its_references(db):
    set_row, (card,) = _set_with_cards(db, "4")
    ensure_placeholders(db, set_row.id)
    db.flush()
    placeholder = _variants(db, card)["unpriced"]
    collection = Collection(name="Mine")
    binder = Binder(name="Binder")
    goal = Goal(name="Custom", goal_type=GoalType.CUSTOM)
    db.add_all([collection, binder, goal])
    db.flush()
    db.add_all([
        CollectionItem(collection_id=collection.id, card_variant_id=placeholder.id, quantity=2),
        BinderPlacement(
            binder_id=binder.id, page_index=0, row=0, col=0, kind=PlacementKind.CARD,
            card_variant_id=placeholder.id,
        ),
        GoalItem(goal_id=goal.id, card_variant_id=placeholder.id),
    ])
    db.commit()

    products = [ProductDTO(10, 1, "Card 4", "Card 4", None, None, "4/102", None)]
    prices = {10: [PricePointDTO(10, "Holofoil", date(2026, 10, 25), None, None, None, 9.0, None)]}
    _derive_variants(db, set_row, products, prices)
    db.commit()

    variants = _variants(db, card)
    assert set(variants) == {"holofoil"}
    holo = variants["holofoil"]
    assert holo.is_canonical
    assert db.scalar(select(CollectionItem.card_variant_id)) == holo.id
    assert db.scalar(select(CollectionItem.quantity)) == 2
    assert db.scalar(select(BinderPlacement.card_variant_id)) == holo.id
    assert db.scalar(select(GoalItem.card_variant_id)) == holo.id


def test_retiring_drops_a_goal_row_the_real_printing_already_has(db):
    set_row, (card,) = _set_with_cards(db, "1")
    ensure_placeholders(db, set_row.id)
    db.flush()
    placeholder = _variants(db, card)["unpriced"]
    real = CardVariant(card_id=card.id, variant="normal", is_canonical=False)
    goal = Goal(name="Custom", goal_type=GoalType.CUSTOM)
    db.add_all([real, goal])
    db.flush()
    db.add_all([
        GoalItem(goal_id=goal.id, card_variant_id=placeholder.id),
        GoalItem(goal_id=goal.id, card_variant_id=real.id),
    ])
    db.commit()

    assert retire_placeholders(db, [card.id]) == 1
    db.commit()
    assert db.execute(select(GoalItem.card_variant_id)).scalars().all() == [real.id]
    assert real.is_canonical  # took over the placeholder's canonical flag


def test_retire_leaves_a_card_with_no_real_printing_alone(db):
    set_row, (card,) = _set_with_cards(db, "1")
    ensure_placeholders(db, set_row.id)
    db.commit()
    assert retire_placeholders(db, [card.id]) == 0
    assert set(_variants(db, card)) == {"unpriced"}
