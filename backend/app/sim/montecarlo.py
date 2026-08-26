"""Vectorised Monte Carlo engine. The primary source of truth.

PERFORMANCE CONTRACT: 100,000 trials of a 36-pack box over a ~200-card set in under 2 seconds.
That is only reachable by drawing all trials at once against integer card indices. A per-pack
Python loop is roughly 100x too slow and will make the UI unusable -- design for NumPy from
the first line rather than optimising later.

Scatter-adding pulled cards into a (n_trials, n_pool) count matrix uses `np.bincount` on a flat
`trial*n_pool + card` index, not `np.add.at` (unbuffered, much slower at this scale): every hit
across every slot/repeat/guarantee is appended to one list and bincount'd once at the end.
"""
import numpy as np

from app.sim.types import BoxSpec, CardPool, CostParams, SimResult, Strategy


def _draw_box_guarantees(
    box: BoxSpec, pool: CardPool, n_boxes: int, n_trials: int, rng: np.random.Generator
) -> np.ndarray | None:
    """Sample without replacement from each guaranteed rarity's pool, per (trial, box) instance,
    and ADD the result on top of the independent slot draws in `draw_boxes` -- a documented
    simplification (see docs/06-roadmap.md's 2.7 shipped note): this does not renormalise the
    regular slot outcomes to exclude the now-satisfied guarantee, so in the rare case the same
    rarity is also hit by an ordinary slot roll in the same box, that box can end up with one
    more copy than a strictly collated model would produce. No real `box_constraint` data exists
    yet to make getting this exactly right the load-bearing gap it will eventually be.

    Returns flat `trial*n_pool + card` indices (one per guaranteed hit), or None if there are no
    guarantees or no candidate cards for any of them.
    """
    if not box.guarantees:
        return None
    n_pool = len(pool.variant_ids)
    hits: list[np.ndarray] = []
    for rarity_idx, (lo, hi) in box.guarantees.items():
        candidates = np.flatnonzero(pool.rarity_index == rarity_idx)
        if candidates.size == 0:
            continue
        n_instances = n_trials * n_boxes
        target = (
            np.full(n_instances, lo, dtype=np.int64)
            if lo == hi
            else rng.integers(lo, hi + 1, size=n_instances)
        )
        target = np.minimum(target, candidates.size)

        # Random-key argsort: sorting each row's random keys gives a uniform random permutation
        # of column positions: the first target[row] of them is a uniform sample without
        # replacement, drawn for every (trial, box) instance in one vectorised pass.
        keys = rng.random((n_instances, candidates.size))
        order = np.argsort(keys, axis=1)
        positions = np.arange(candidates.size)[None, :]
        take_mask = positions < target[:, None]
        instance_idx, position_idx = np.nonzero(take_mask)
        chosen_cards = candidates[order[instance_idx, position_idx]]

        trial_of_instance = instance_idx // n_boxes
        hits.append(trial_of_instance.astype(np.int64) * n_pool + chosen_cards)
    if not hits:
        return None
    return np.concatenate(hits)


def draw_boxes(
    box: BoxSpec, pool: CardPool, n_boxes: int, n_trials: int, rng: np.random.Generator
) -> np.ndarray:
    """Return a (n_trials, n_pool) int16 count matrix of cards pulled.

    Order of operations matters:
      1. draw guaranteed hits per box WITHOUT replacement from their rarity pool
      2. assign them to distinct packs
      3. fill remaining slots from the renormalised slot distributions

    Step 2/3's "distinct packs" and "renormalised" nuances are approximated: guarantees are
    additive on top of independent slot draws rather than replacing/renormalising them (see
    `_draw_box_guarantees`'s docstring) -- aggregate per-box counts are all `draw_boxes` returns,
    so no per-pack bookkeeping is needed regardless.
    """
    n_pool = len(pool.variant_ids)
    n_packs = box.packs_per_box * n_boxes
    if n_pool == 0 or n_packs == 0 or n_trials == 0:
        return np.zeros((n_trials, n_pool), dtype=np.int16)

    variant_lookup = {name: i for i, name in enumerate(pool.variants)}
    flat_hits: list[np.ndarray] = []

    for slot in box.pack.slots:
        candidates_per_outcome = []
        for rarity_idx, variant in zip(slot.rarity_indices, slot.variants, strict=True):
            variant_idx = variant_lookup.get(variant)
            if variant_idx is None:
                candidates_per_outcome.append(np.empty(0, dtype=np.int64))
                continue
            mask = (pool.rarity_index == rarity_idx) & (pool.variant_index == variant_idx)
            candidates_per_outcome.append(np.flatnonzero(mask))

        n_outcomes = len(slot.probabilities)
        for _ in range(slot.repeat):
            if n_outcomes == 1:
                outcome_idx = np.zeros((n_trials, n_packs), dtype=np.int64)
            else:
                outcome_idx = rng.choice(
                    n_outcomes, size=(n_trials, n_packs), p=slot.probabilities
                )
            for i, candidates in enumerate(candidates_per_outcome):
                if candidates.size == 0:
                    continue
                cell_mask = outcome_idx == i
                n_hits = int(cell_mask.sum())
                if n_hits == 0:
                    continue
                trial_idx = np.nonzero(cell_mask)[0]
                chosen_cards = candidates[rng.integers(0, candidates.size, size=n_hits)]
                flat_hits.append(trial_idx.astype(np.int64) * n_pool + chosen_cards)

    guarantee_hits = _draw_box_guarantees(box, pool, n_boxes, n_trials, rng)
    if guarantee_hits is not None:
        flat_hits.append(guarantee_hits)

    if not flat_hits:
        return np.zeros((n_trials, n_pool), dtype=np.int16)

    flat = np.concatenate(flat_hits)
    counts = np.bincount(flat, minlength=n_trials * n_pool).reshape(n_trials, n_pool)
    return counts.astype(np.int16)


def singles_cost(needed_mask: np.ndarray, pool: CardPool, params: CostParams) -> np.ndarray:
    """Vectorised over trials. `needed_mask` is (n_trials, n_pool) bool: still needed after this
    trial's pulls. Mirrors services/costs.singles_cost's seller-consolidation shipping model in
    float (money stays Decimal at that boundary; the simulator is float throughout per
    CLAUDE.md's carve-out)."""
    subtotal = (needed_mask * pool.prices[None, :]).sum(axis=1)
    n_needed = needed_mask.sum(axis=1)
    orders = np.ceil(n_needed / params.cards_per_order)
    shipping = orders * params.shipping_per_order
    tax = subtotal * params.sales_tax_rate
    return subtotal + shipping + tax


def liquidation_value(dupes: np.ndarray, pool: CardPool, params: CostParams) -> np.ndarray:
    """Duplicates net resale, floored at zero below params.resale_floor. Recomputed from
    pool.prices + params here rather than a fixed pool.resale field -- liquidation_rate and
    resale_floor are exactly what sensitivity analysis (2.14) perturbs, and baking resale into
    the pool at build time would make that perturbation silently do nothing."""
    resale_per_card = np.where(
        pool.prices >= params.resale_floor, pool.prices * params.liquidation_rate, 0.0
    )
    return (dupes * resale_per_card[None, :]).sum(axis=1)


def simulate(
    strategy: Strategy,
    pool: CardPool,
    boxes: dict[int, BoxSpec],
    params: CostParams,
    n_trials: int = 20_000,
    seed: int = 0,
) -> SimResult:
    """NetCost = SealedCost + SinglesCost(remaining) - Liquidation(dupes)."""
    rng = np.random.default_rng(seed)
    n_pool = len(pool.variant_ids)
    pulled = np.zeros((n_trials, n_pool), dtype=np.int64)
    sealed_subtotal = 0.0
    any_sealed = False

    for sealed_product_id, qty in strategy.units.items():
        if qty <= 0:
            continue
        any_sealed = True
        box = boxes[sealed_product_id]
        pulled += draw_boxes(box, pool, n_boxes=qty, n_trials=n_trials, rng=rng)
        sealed_subtotal += box.unit_price * qty

    sealed_cost = sealed_subtotal * (1.0 + params.sales_tax_rate)
    if any_sealed:
        sealed_cost += params.sealed_shipping

    needed_broadcast = np.broadcast_to(pool.needed, pulled.shape)
    still_needed_mask = needed_broadcast & (pulled == 0)
    dupes = np.maximum(pulled - pool.needed.astype(np.int64)[None, :], 0)

    singles = singles_cost(still_needed_mask, pool, params)
    liquidation = liquidation_value(dupes, pool, params)
    net_cost = sealed_cost + singles - liquidation

    p_complete = float((~still_needed_mask.any(axis=1)).mean())
    expected_cards_remaining = float(still_needed_mask.sum(axis=1).mean())

    counts, edges = np.histogram(net_cost, bins=30)

    return SimResult(
        mean=float(net_cost.mean()),
        sd=float(net_cost.std(ddof=1)) if n_trials > 1 else 0.0,
        p10=float(np.percentile(net_cost, 10)),
        p50=float(np.percentile(net_cost, 50)),
        p90=float(np.percentile(net_cost, 90)),
        p95=float(np.percentile(net_cost, 95)),
        p_complete_from_sealed=p_complete,
        expected_cards_remaining=expected_cards_remaining,
        histogram=(counts, edges),
        n_trials=n_trials,
        seed=seed,
    )
