"""Placeholder printings for cards the price feed has not priced yet.

Goals, binders and the collection all point at `card_variant`, and variants are derived from the
price feed -- so a card TCGplayer doesn't list (or that the matcher can't pin down yet) would have
nothing to point at. Every such card gets one `unpriced` row instead: no product id, so no price,
canonical so a set goal counts it. The rest of the app already treats a variant with no price as
"unpriced", never as $0.

When the price ingest later derives real printings for the card, `retire_placeholders` moves
everything that referenced the placeholder (collection items, goal items, binder pockets) onto the
card's canonical printing and deletes the placeholder.
"""
import logging

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import BinderPlacement, Card, CardVariant, CollectionItem, GoalItem
from app.models.enums import Variant

log = logging.getLogger(__name__)


def ensure_placeholders(db: Session, set_id: int | None = None) -> int:
    """Give every card (in `set_id`, or everywhere) that has no printing an `unpriced` one."""
    has_variant = select(CardVariant.id).where(CardVariant.card_id == Card.id).exists()
    stmt = select(Card.id).where(~has_variant)
    if set_id is not None:
        stmt = stmt.where(Card.set_id == set_id)
    card_ids = list(db.execute(stmt).scalars())
    db.add_all(
        CardVariant(card_id=card_id, variant=Variant.UNPRICED, is_canonical=True, is_special=False)
        for card_id in card_ids
    )
    return len(card_ids)


def retire_placeholders(db: Session, card_ids: list[int]) -> int:
    """Drop the placeholder of every card in `card_ids` that now has a real printing, moving its
    references to the canonical printing (or the first in-set one if none is canonical, which is
    then made canonical so a set goal still counts the card)."""
    if not card_ids:
        return 0
    db.flush()
    placeholders = {
        v.card_id: v
        for v in db.execute(
            select(CardVariant).where(
                CardVariant.card_id.in_(card_ids), CardVariant.variant == Variant.UNPRICED
            )
        ).scalars()
    }
    if not placeholders:
        return 0
    real: dict[int, list[CardVariant]] = {}
    for v in db.execute(
        select(CardVariant)
        .where(
            CardVariant.card_id.in_(placeholders.keys()),
            CardVariant.variant != Variant.UNPRICED,
        )
        .order_by(CardVariant.is_canonical.desc(), CardVariant.is_special, CardVariant.id)
    ).scalars():
        real.setdefault(v.card_id, []).append(v)

    n_retired = 0
    for card_id, placeholder in placeholders.items():
        if card_id not in real:
            continue
        target = real[card_id][0]
        target.is_canonical = target.is_canonical or placeholder.is_canonical
        _move_references(db, placeholder.id, target.id)
        db.delete(placeholder)
        n_retired += 1
    if n_retired:
        log.info("Retired %d placeholder printings now that real ones exist", n_retired)
    return n_retired


def _move_references(db: Session, old_id: int, new_id: int) -> None:
    db.execute(
        update(CollectionItem)
        .where(CollectionItem.card_variant_id == old_id)
        .values(card_variant_id=new_id)
    )
    db.execute(
        update(BinderPlacement)
        .where(BinderPlacement.card_variant_id == old_id)
        .values(card_variant_id=new_id)
    )
    # goal_item is unique per (goal, variant): a goal that already lists the target just loses
    # the placeholder's row.
    already = select(GoalItem.goal_id).where(GoalItem.card_variant_id == new_id)
    db.execute(
        delete(GoalItem).where(GoalItem.card_variant_id == old_id, GoalItem.goal_id.in_(already))
    )
    db.execute(
        update(GoalItem).where(GoalItem.card_variant_id == old_id).values(card_variant_id=new_id)
    )
