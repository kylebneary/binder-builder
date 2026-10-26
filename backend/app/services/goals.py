"""Goal builder + need-list view. Plain dataclasses in/out (see docs/01-architecture.md layer
rules) -- reusable from the CLI and from the sim service layer without pulling in FastAPI.

`goal_item` is materialised (not evaluated on read) per docs/02-data-model.md: the optimizer
hits this table hundreds of thousands of times per simulation and it must be a plain join.
Materialisation here is a wholesale delete-and-reinsert -- goal_item rows are cheap join rows
with no history worth diffing incrementally.

CUSTOM goals are the exception: they have no rule to materialise from, so their goal_item rows
are the source of truth and are only ever changed by `edit_goal_items`.
"""
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ingest.printing_tags import printing_label
from app.models import Card, CardVariant, CollectionItem, Goal, GoalItem, Set
from app.models.enums import Condition, GoalType
from app.services.cards import CardQuery, variant_ids
from app.services.costs import CostParams, SinglesCostBreakdown, singles_cost
from app.services.prices import get_current_prices


class GoalEditError(ValueError):
    """An edit that names cards that do not exist, or a goal definition that makes no sense."""


class GoalTypeError(GoalEditError):
    """A hand edit on a goal whose items are derived from a rule. The goal is fine; the request
    conflicts with its type, which is why the API answers 409 rather than 422."""


def _set_variant_ids(db: Session, set_id: int | None, goal_type: GoalType) -> list[int]:
    if set_id is None:
        return []
    stmt = select(CardVariant.id).join(Card, CardVariant.card_id == Card.id).where(
        Card.set_id == set_id
    )
    if goal_type == GoalType.SET:
        stmt = stmt.where(CardVariant.is_canonical.is_(True))
    elif goal_type == GoalType.MASTER_SET:
        stmt = stmt.where(CardVariant.is_special.is_(False))
    return list(db.execute(stmt).scalars().all())


def _filter_variant_ids(db: Session, filter_json: dict | None) -> list[int]:
    """A filter goal holds whatever the card search would return for its stored query, so the
    two can never disagree. See services/cards.py for the accepted keys; the singular keys older
    goals were saved with (`set_id`, `rarity`, `artist`, `supertype`) are still read.

    Ownership is ignored even if a stored filter mentions it -- see CardQuery.to_goal_filter."""
    query = CardQuery.from_dict(filter_json)
    query.owned = None
    query.goal_id = None
    return variant_ids(db, query)


def _infer_set_id(db: Session, goal: Goal) -> int | None:
    """The one set every item belongs to, else None.

    The optimizer prices sealed product, which is per set, so a goal it can simulate needs a
    `set_id`. Set goals are given one; for filter and custom goals it is derived, so "every
    Charizard in Obsidian Flames" can still be simulated while "every Charizard" cannot.
    """
    set_ids = db.execute(
        select(Card.set_id)
        .join(CardVariant, CardVariant.card_id == Card.id)
        .join(GoalItem, GoalItem.card_variant_id == CardVariant.id)
        .where(GoalItem.goal_id == goal.id)
        .distinct()
    ).scalars().all()
    return set_ids[0] if len(set_ids) == 1 else None


def materialize_goal_items(db: Session, goal: Goal) -> None:
    if goal.goal_type == GoalType.CUSTOM:
        return
    if goal.goal_type in (GoalType.SET, GoalType.MASTER_SET, GoalType.GRAND_MASTER_SET):
        ids = _set_variant_ids(db, goal.set_id, goal.goal_type)
    elif goal.goal_type == GoalType.FILTER:
        ids = _filter_variant_ids(db, goal.filter_json)
    else:
        ids = []

    db.execute(delete(GoalItem).where(GoalItem.goal_id == goal.id))
    for variant_id in ids:
        db.add(GoalItem(goal_id=goal.id, card_variant_id=variant_id, required_qty=1))
    db.flush()
    if goal.goal_type == GoalType.FILTER:
        goal.set_id = _infer_set_id(db, goal)
    db.commit()


def _existing_variant_ids(db: Session, ids: Iterable[int]) -> set[int]:
    wanted = set(ids)
    if not wanted:
        return set()
    return set(db.execute(select(CardVariant.id).where(CardVariant.id.in_(wanted))).scalars())


def create_goal(
    db: Session,
    name: str,
    goal_type: GoalType,
    set_id: int | None = None,
    filter_json: dict | None = None,
    target_condition: Condition = Condition.NM,
    card_variant_ids: Sequence[int] | None = None,
) -> Goal:
    """Create a goal and materialise its items.

    `card_variant_ids` is only read for CUSTOM goals, which start from exactly that list (and
    may start empty, to be filled from the card search).
    """
    if goal_type == GoalType.CUSTOM:
        missing = set(card_variant_ids or []) - _existing_variant_ids(db, card_variant_ids or [])
        if missing:
            raise GoalEditError(f"Unknown card variant ids: {sorted(missing)}")
        set_id = None
    if goal_type == GoalType.FILTER and not CardQuery.from_dict(filter_json).describes_anything():
        raise GoalEditError("A filter goal needs at least one filter -- it would match every card")

    goal = Goal(
        name=name,
        goal_type=goal_type,
        set_id=set_id,
        filter_json=filter_json,
        target_condition=target_condition,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    if goal_type == GoalType.CUSTOM:
        _add_items(db, goal, card_variant_ids or [])
        goal.set_id = _infer_set_id(db, goal)
        db.commit()
    else:
        materialize_goal_items(db, goal)
    db.refresh(goal)
    return goal


def list_goals(db: Session) -> list[Goal]:
    return list(db.execute(select(Goal).order_by(Goal.created_at.desc())).scalars())


def get_goal(db: Session, goal_id: int) -> Goal | None:
    return db.get(Goal, goal_id)


def delete_goal(db: Session, goal_id: int) -> bool:
    goal = db.get(Goal, goal_id)
    if goal is None:
        return False
    db.delete(goal)
    db.commit()
    return True


def resync_goal(db: Session, goal_id: int) -> Goal | None:
    """Re-materialise goal_item, e.g. after new cards land in the set the goal targets. A no-op
    for CUSTOM goals, whose items are not derived from anything."""
    goal = db.get(Goal, goal_id)
    if goal is None:
        return None
    materialize_goal_items(db, goal)
    db.refresh(goal)
    return goal


def _add_items(db: Session, goal: Goal, ids: Iterable[int]) -> int:
    present = set(
        db.execute(select(GoalItem.card_variant_id).where(GoalItem.goal_id == goal.id)).scalars()
    )
    added = 0
    for variant_id in dict.fromkeys(ids):
        if variant_id in present:
            continue
        db.add(GoalItem(goal_id=goal.id, card_variant_id=variant_id, required_qty=1))
        added += 1
    db.flush()
    return added


@dataclass(slots=True)
class GoalItemsEdit:
    added: int
    removed: int
    item_count: int


def edit_goal_items(
    db: Session, goal_id: int, add: Iterable[int] = (), remove: Iterable[int] = ()
) -> GoalItemsEdit | None:
    """Add and remove cards on a CUSTOM goal. Adding a card already present is not an error.

    Other goal types refuse: their items are re-derived on every resync, so a hand edit would
    silently vanish. `convert_to_custom` is the explicit way to take over a rule-built list.
    """
    goal = db.get(Goal, goal_id)
    if goal is None:
        return None
    if goal.goal_type != GoalType.CUSTOM:
        raise GoalTypeError(
            f"Goal {goal_id} is a {goal.goal_type} goal, built by a rule; convert it to a custom "
            "goal before editing its cards by hand"
        )
    add_ids = list(add)
    missing = set(add_ids) - _existing_variant_ids(db, add_ids)
    if missing:
        raise GoalEditError(f"Unknown card variant ids: {sorted(missing)}")

    remove_ids = set(remove)
    removed = 0
    if remove_ids:
        doomed = GoalItem.goal_id == goal_id, GoalItem.card_variant_id.in_(remove_ids)
        removed = len(db.execute(select(GoalItem.id).where(*doomed)).all())
        db.execute(delete(GoalItem).where(*doomed))
    added = _add_items(db, goal, (i for i in add_ids if i not in remove_ids))
    goal.set_id = _infer_set_id(db, goal)
    db.commit()

    count = len(db.execute(select(GoalItem.id).where(GoalItem.goal_id == goal_id)).all())
    return GoalItemsEdit(added=added, removed=removed, item_count=count)


def convert_to_custom(db: Session, goal_id: int) -> Goal | None:
    """Freeze a rule-built goal's current items into a CUSTOM goal so they can be hand-edited.

    `filter_json` is kept as a record of where the list started; nothing reads it once the goal
    is custom. `set_id` is re-derived from the items, which for a set goal leaves it unchanged.
    """
    goal = db.get(Goal, goal_id)
    if goal is None:
        return None
    goal.goal_type = GoalType.CUSTOM
    goal.set_id = _infer_set_id(db, goal)
    db.commit()
    db.refresh(goal)
    return goal


@dataclass(slots=True)
class NeedItem:
    card_variant_id: int
    card_name: str
    number: str
    rarity: str | None
    variant: str
    required_qty: int
    owned_qty: int
    need_qty: int
    market_price: Decimal | None
    set_name: str = ""
    ptcg_set_id: str = ""
    image_small: str | None = None
    variant_label: str | None = None  # tagged printings only, e.g. "Prerelease stamp"


@dataclass(slots=True)
class GoalDetail:
    id: int
    name: str
    goal_type: str
    set_id: int | None
    target_condition: str
    filter_json: dict | None = None
    items: list[NeedItem] = field(default_factory=list)
    cost: SinglesCostBreakdown = field(
        default_factory=lambda: SinglesCostBreakdown(
            0, Decimal("0"), 0, Decimal("0"), Decimal("0"), Decimal("0")
        )
    )
    unpriced_count: int = 0


def get_goal_need_list(
    db: Session, goal_id: int, collection_id: int, params: CostParams | None = None
) -> GoalDetail | None:
    goal = db.get(Goal, goal_id)
    if goal is None:
        return None

    rows = db.execute(
        select(GoalItem, CardVariant, Card, Set)
        .join(CardVariant, GoalItem.card_variant_id == CardVariant.id)
        .join(Card, CardVariant.card_id == Card.id)
        .join(Set, Card.set_id == Set.id)
        .where(GoalItem.goal_id == goal_id)
        .order_by(
            Set.release_date.asc().nulls_last(),
            Set.id,
            Card.number_sort,
            Card.number,
            CardVariant.id,
        )
    ).all()

    variant_ids_in_goal = [gi.card_variant_id for gi, _, _, _ in rows]
    owned_by_variant: dict[int, int] = {}
    if variant_ids_in_goal:
        owned_rows = db.execute(
            select(CollectionItem.card_variant_id, CollectionItem.quantity).where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.card_variant_id.in_(variant_ids_in_goal),
            )
        ).all()
        for card_variant_id, qty in owned_rows:
            owned_by_variant[card_variant_id] = owned_by_variant.get(card_variant_id, 0) + qty

    product_ids = sorted(
        {cv.tcgplayer_product_id for _, cv, _, _ in rows if cv.tcgplayer_product_id}
    )
    prices = get_current_prices(db, product_ids)

    items: list[NeedItem] = []
    need_prices: list[Decimal] = []
    unpriced_count = 0
    for goal_item, variant, card, set_row in rows:
        owned = owned_by_variant.get(variant.id, 0)
        need = max(goal_item.required_qty - owned, 0)
        price = None
        if variant.tcgplayer_product_id is not None and variant.tcgplayer_sub_type_name is not None:
            current = prices.get((variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name))
            if current:
                price = current["market"]
        items.append(
            NeedItem(
                card_variant_id=variant.id,
                card_name=card.name,
                number=card.number,
                rarity=card.rarity,
                variant=str(variant.variant),
                required_qty=goal_item.required_qty,
                owned_qty=owned,
                need_qty=need,
                market_price=price,
                set_name=set_row.name,
                ptcg_set_id=set_row.ptcg_set_id,
                image_small=card.image_small,
                variant_label=printing_label(str(variant.variant)),
            )
        )
        if need > 0:
            if price is not None:
                need_prices.extend([price] * need)
            else:
                unpriced_count += 1

    cost = singles_cost(need_prices, params)

    return GoalDetail(
        id=goal.id,
        name=goal.name,
        goal_type=str(goal.goal_type),
        set_id=goal.set_id,
        target_condition=str(goal.target_condition),
        filter_json=goal.filter_json,
        items=items,
        cost=cost,
        unpriced_count=unpriced_count,
    )


def mass_entry_text(detail: GoalDetail) -> str:
    """TCGplayer Mass Entry format: one '<qty> <card name>' line per still-needed item. Used by
    both `bb goal export-mass-entry` and `GET /goals/{id}/export/mass-entry` so the formatting
    logic lives in one place rather than duplicated between the CLI and the UI's download."""
    lines = [f"{item.need_qty} {item.card_name}" for item in detail.items if item.need_qty > 0]
    return "\n".join(lines) + ("\n" if lines else "")
