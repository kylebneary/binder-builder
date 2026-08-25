"""Goal builder + need-list view. Plain dataclasses in/out (see docs/01-architecture.md layer
rules) -- reusable from the CLI and from the sim service layer without pulling in FastAPI.

`goal_item` is materialised (not evaluated on read) per docs/02-data-model.md: the optimizer
hits this table hundreds of thousands of times per simulation and it must be a plain join.
Materialisation here is a wholesale delete-and-reinsert -- goal_item rows are cheap join rows
with no history worth diffing incrementally.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Card, CardVariant, CollectionItem, Goal, GoalItem
from app.models.enums import Condition, GoalType
from app.services.costs import CostParams, SinglesCostBreakdown, singles_cost
from app.services.prices import get_current_prices


def _set_variants(db: Session, set_id: int | None, *, canonical_only: bool) -> list[CardVariant]:
    if set_id is None:
        return []
    stmt = select(CardVariant).join(Card, CardVariant.card_id == Card.id).where(
        Card.set_id == set_id
    )
    if canonical_only:
        stmt = stmt.where(CardVariant.is_canonical.is_(True))
    return list(db.execute(stmt).scalars().all())


def _filter_variants(db: Session, filter_json: dict) -> list[CardVariant]:
    """Minimal AND-filter over set_id/rarity/artist/supertype, matched against canonical
    variants only (mirrors the "owned" definition in services/sets.py's CardView.is_owned).
    A full filter-builder is out of scope for this slice; extend the accepted keys here as the
    UI grows to support them."""
    stmt = select(CardVariant).join(Card, CardVariant.card_id == Card.id).where(
        CardVariant.is_canonical.is_(True)
    )
    if filter_json.get("set_id") is not None:
        stmt = stmt.where(Card.set_id == filter_json["set_id"])
    if filter_json.get("rarity"):
        stmt = stmt.where(Card.rarity.in_(filter_json["rarity"]))
    if filter_json.get("artist"):
        stmt = stmt.where(Card.artist.in_(filter_json["artist"]))
    if filter_json.get("supertype"):
        stmt = stmt.where(Card.supertype.in_(filter_json["supertype"]))
    return list(db.execute(stmt).scalars().all())


def materialize_goal_items(db: Session, goal: Goal) -> None:
    if goal.goal_type == GoalType.SET:
        variants = _set_variants(db, goal.set_id, canonical_only=True)
    elif goal.goal_type == GoalType.MASTER_SET:
        variants = _set_variants(db, goal.set_id, canonical_only=False)
    elif goal.goal_type == GoalType.FILTER:
        variants = _filter_variants(db, goal.filter_json or {})
    else:
        variants = []

    db.execute(delete(GoalItem).where(GoalItem.goal_id == goal.id))
    for v in variants:
        db.add(GoalItem(goal_id=goal.id, card_variant_id=v.id, required_qty=1))
    db.commit()


def create_goal(
    db: Session,
    name: str,
    goal_type: GoalType,
    set_id: int | None = None,
    filter_json: dict | None = None,
    target_condition: Condition = Condition.NM,
) -> Goal:
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
    """Re-materialise goal_item, e.g. after new cards land in the set the goal targets."""
    goal = db.get(Goal, goal_id)
    if goal is None:
        return None
    materialize_goal_items(db, goal)
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


@dataclass(slots=True)
class GoalDetail:
    id: int
    name: str
    goal_type: str
    set_id: int | None
    target_condition: str
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
        select(GoalItem, CardVariant, Card)
        .join(CardVariant, GoalItem.card_variant_id == CardVariant.id)
        .join(Card, CardVariant.card_id == Card.id)
        .where(GoalItem.goal_id == goal_id)
        .order_by(Card.number_sort, Card.number)
    ).all()

    variant_ids = [gi.card_variant_id for gi, _, _ in rows]
    owned_by_variant: dict[int, int] = {}
    if variant_ids:
        owned_rows = db.execute(
            select(CollectionItem.card_variant_id, CollectionItem.quantity).where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.card_variant_id.in_(variant_ids),
            )
        ).all()
        for card_variant_id, qty in owned_rows:
            owned_by_variant[card_variant_id] = owned_by_variant.get(card_variant_id, 0) + qty

    product_ids = sorted({cv.tcgplayer_product_id for _, cv, _ in rows if cv.tcgplayer_product_id})
    prices = get_current_prices(db, product_ids)

    items: list[NeedItem] = []
    need_prices: list[Decimal] = []
    unpriced_count = 0
    for goal_item, variant, card in rows:
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
        items=items,
        cost=cost,
        unpriced_count=unpriced_count,
    )
