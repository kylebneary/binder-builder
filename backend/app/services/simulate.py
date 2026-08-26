"""DB <-> sim boundary. `sim/` never sees a Session (docs/01-architecture.md) -- this module is
the only place that translates ORM rows into the plain dataclasses `app/sim/*` consumes.

Reads already-synced `PullRateProfile`/`PackSlot`/`SlotOutcome`/`BoxConstraint` rows, not the
YAML -- `app/ingest/pullrates.py` is what turns YAML into those rows; by simulation time the DB
is the source the spec calls "a cache of it."
"""
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Card,
    CardVariant,
    CollectionItem,
    GoalItem,
    PullRateProfile,
    SealedProduct,
)
from app.services.prices import get_current_prices
from app.sim.types import BoxSpec, CardPool, PackSpec, SlotSpec


def _profile_rarities(profile: PullRateProfile) -> set[str]:
    rarities = {o.rarity for slot in profile.slots for o in slot.outcomes}
    rarities |= {bc.rarity for bc in profile.box_constraints}
    return rarities


@dataclass(slots=True)
class PoolBuildResult:
    pool: CardPool
    unpriced_needed_count: int
    # Needed cards whose rarity has no slot_outcome/box_constraint coverage in this profile at
    # all (e.g. a promo rarity, or the unmodeled "Foil Energy" slot some SV-era YAMLs note) --
    # the simulator can never produce them from any strategy, sealed or not. Their price is a
    # constant floor every strategy's NetCost must include; callers (services/simulation_runs.py)
    # add it as a flat offset rather than folding it into the per-trial shipping-order math, so
    # this stays a documented approximation at the shipping boundary, not a hidden gap in the
    # total. See docs/06-roadmap.md's 2.7 shipped note.
    uncovered_needed_price_sum: Decimal


def build_card_pool(
    db: Session, set_id: int, profile: PullRateProfile, goal_id: int, collection_id: int
) -> PoolBuildResult:
    """Pool scope = every card_variant in the set matching a slot_outcome's (rarity, variant), or
    any variant of a box_constraint's rarity (a box guarantee isn't scoped to one variant).
    `needed` mirrors services/goals.get_goal_need_list's definition: owned via `CollectionItem`,
    priced via `services/prices.get_current_prices`; an unpriced needed card is excluded from
    `needed` and counted in `unpriced_needed_count`, never silently priced at 0.
    """
    wanted_rarities = _profile_rarities(profile)
    outcome_pairs = {(o.rarity, o.variant) for slot in profile.slots for o in slot.outcomes}
    box_rarities = {bc.rarity for bc in profile.box_constraints}

    pool_rows = db.execute(
        select(CardVariant, Card)
        .join(Card, CardVariant.card_id == Card.id)
        .where(Card.set_id == set_id, Card.rarity.in_(wanted_rarities))
    ).all()
    selected = [
        (v, c)
        for v, c in pool_rows
        if (c.rarity, str(v.variant)) in outcome_pairs or c.rarity in box_rarities
    ]
    in_scope_ids = {v.id for v, _ in selected}

    goal_rows = db.execute(
        select(GoalItem, CardVariant, Card)
        .join(CardVariant, GoalItem.card_variant_id == CardVariant.id)
        .join(Card, CardVariant.card_id == Card.id)
        .where(GoalItem.goal_id == goal_id)
    ).all()

    all_variant_ids = sorted(in_scope_ids | {v.id for _, v, _ in goal_rows})
    owned_by_variant: dict[int, int] = {}
    if all_variant_ids:
        for card_variant_id, qty in db.execute(
            select(CollectionItem.card_variant_id, CollectionItem.quantity).where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.card_variant_id.in_(all_variant_ids),
            )
        ).all():
            owned_by_variant[card_variant_id] = owned_by_variant.get(card_variant_id, 0) + qty

    product_ids = sorted(
        {v.tcgplayer_product_id for v, _ in selected if v.tcgplayer_product_id}
        | {v.tcgplayer_product_id for _, v, _ in goal_rows if v.tcgplayer_product_id}
    )
    prices = get_current_prices(db, product_ids)

    def _price(variant: CardVariant) -> Decimal | None:
        if variant.tcgplayer_product_id is None or variant.tcgplayer_sub_type_name is None:
            return None
        current = prices.get((variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name))
        return current["market"] if current else None

    required_by_variant = {v.card_variant_id: v.required_qty for v, _, _ in goal_rows}

    rarities_list = sorted(wanted_rarities)
    variants_list = sorted(
        {str(v.variant) for v, _ in selected}
        | {o.variant for slot in profile.slots for o in slot.outcomes}
    )
    rarity_pos = {r: i for i, r in enumerate(rarities_list)}
    variant_pos = {v: i for i, v in enumerate(variants_list)}

    n = len(selected)
    variant_ids = np.array([v.id for v, _ in selected], dtype=np.int64)
    rarity_index = np.array([rarity_pos[c.rarity] for _, c in selected], dtype=np.int32)
    variant_index = np.array([variant_pos[str(v.variant)] for v, _ in selected], dtype=np.int32)
    prices_arr = np.zeros(n, dtype=np.float64)
    needed = np.zeros(n, dtype=bool)
    unpriced_needed_count = 0

    for i, (variant, _card) in enumerate(selected):
        price = _price(variant)
        if price is not None:
            prices_arr[i] = float(price)
        required = required_by_variant.get(variant.id, 0)
        owned = owned_by_variant.get(variant.id, 0)
        if required - owned > 0:
            if price is None:
                unpriced_needed_count += 1
            else:
                needed[i] = True

    uncovered_needed_price_sum = Decimal("0")
    for goal_item, variant, _card in goal_rows:
        if variant.id in in_scope_ids:
            continue
        owned = owned_by_variant.get(variant.id, 0)
        if goal_item.required_qty - owned <= 0:
            continue
        price = _price(variant)
        if price is not None:
            uncovered_needed_price_sum += price

    pool = CardPool(
        variant_ids=variant_ids,
        prices=prices_arr,
        resale=np.zeros(n, dtype=np.float64),
        rarity_index=rarity_index,
        variant_index=variant_index,
        needed=needed,
        rarities=rarities_list,
        variants=variants_list,
    )
    return PoolBuildResult(
        pool=pool,
        unpriced_needed_count=unpriced_needed_count,
        uncovered_needed_price_sum=uncovered_needed_price_sum,
    )


def resolve_pull_rate_profile(db: Session, sealed_product: SealedProduct) -> PullRateProfile | None:
    """`pack_config_id` if explicitly set, else the target set's `is_default` profile. Nothing
    currently sets `pack_config_id` (a real, harmless gap -- see docs/06-roadmap.md's 2.7 shipped
    note), so the default-profile fallback is what every real lookup uses today; the explicit
    field stays honored for when a set someday has more than one profile.
    """
    if sealed_product.pack_config_id is not None:
        return db.get(PullRateProfile, sealed_product.pack_config_id)
    if sealed_product.set_id is None:
        return None
    return db.execute(
        select(PullRateProfile).where(
            PullRateProfile.set_id == sealed_product.set_id,
            PullRateProfile.is_default.is_(True),
        )
    ).scalars().first()


def build_box_spec(
    db: Session, sealed_product: SealedProduct, pool: CardPool, unit_price: Decimal | None
) -> BoxSpec | None:
    """None if this product can't be simulated -- no known pack count or no resolvable profile.
    The caller must report that, never guess a pack count or profile.

    `pool` must have been built from the same profile this resolves to (via `build_card_pool`
    against `resolve_pull_rate_profile(db, sealed_product)`) -- this function only maps that
    profile's rows into `PackSpec`/`BoxSpec`, it doesn't re-derive pool scope.
    """
    if not sealed_product.packs_per_unit:
        return None
    profile = resolve_pull_rate_profile(db, sealed_product)
    if profile is None:
        return None

    slots = [
        SlotSpec(
            label=slot.label,
            repeat=slot.repeat,
            rarity_indices=np.array(
                [pool.rarities.index(o.rarity) for o in slot.outcomes], dtype=np.int32
            ),
            probabilities=np.array([o.probability for o in slot.outcomes], dtype=np.float64),
            variants=[o.variant for o in slot.outcomes],
        )
        for slot in profile.slots
    ]
    pack = PackSpec(cards_per_pack=profile.cards_per_pack, slots=slots)

    guarantees: dict[int, tuple[int, int]] = {}
    for bc in profile.box_constraints:
        if bc.rarity not in pool.rarities:
            continue
        idx = pool.rarities.index(bc.rarity)
        if bc.exact_per_box is not None:
            guarantees[idx] = (bc.exact_per_box, bc.exact_per_box)
        elif bc.min_per_box is not None or bc.max_per_box is not None:
            lo = bc.min_per_box or 0
            hi = bc.max_per_box if bc.max_per_box is not None else lo
            guarantees[idx] = (lo, hi)

    return BoxSpec(
        packs_per_box=sealed_product.packs_per_unit,
        pack=pack,
        unit_price=float(unit_price) if unit_price is not None else 0.0,
        guarantees=guarantees,
    )


def sealed_unit_price(db: Session, sealed_product: SealedProduct) -> Decimal | None:
    """A sealed product's own current price. tcgcsv's `subTypeName` is null for sealed goods and
    `app/ingest/tcgcsv.py` defaults it to "Normal" on ingest, so that's the fixed lookup key --
    not derived from `CardVariant` at all, sealed products have none.
    """
    prices = get_current_prices(db, [sealed_product.tcgplayer_product_id])
    current = prices.get((sealed_product.tcgplayer_product_id, "Normal"))
    return current["market"] if current else None
