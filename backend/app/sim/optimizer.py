"""Strategy search over sealed-product quantities.

The objective is a simulation output and is not linear -- do not reach for an MIP solver.
Grid search for <=2 product types (typically <400 simulations); greedy marginal analysis beyond.
Always evaluate and report the singles-only baseline alongside the winner.
"""
from dataclasses import replace
from enum import StrEnum

from app.sim.montecarlo import simulate
from app.sim.types import BoxSpec, CardPool, CostParams, SimResult, Strategy


class Objective(StrEnum):
    MIN_EXPECTED_COST = "min_expected_cost"
    MIN_P90_COST = "min_p90_cost"
    MAX_COMPLETION_UNDER_BUDGET = "max_completion_under_budget"
    MIN_COST_FOR_TARGET_COMPLETION = "min_cost_for_target_completion"


def _p_cost_le(result: SimResult, budget: float) -> float:
    """Approximate P(NetCost <= budget) from the result's histogram bins (SimResult keeps no
    raw per-trial array). A bin is counted only if its whole width is <= budget, so this is a
    conservative (slightly low) estimate, never an overclaim."""
    counts, edges = result.histogram
    total = int(counts.sum())
    if total == 0:
        return 1.0
    included = counts[edges[1:] <= budget].sum()
    return float(included / total)


def _objective_key(
    objective: Objective,
    result: SimResult,
    budget: float | None,
    confidence: float,
) -> float:
    """Lower is always better, so every objective can be minimised/sorted uniformly. Infeasible
    strategies (constraint violated) sort last via +inf rather than being silently dropped --
    the caller can still see and report them.

    MAX_COMPLETION_UNDER_BUDGET and MIN_COST_FOR_TARGET_COMPLETION both use
    `p_complete_from_sealed` (fully complete, not a fractional completion %) as "completion" --
    SimResult doesn't retain a per-trial completion-fraction distribution, so this is a documented
    simplification, not the fully general reading of the spec's objective table.
    """
    if objective is Objective.MIN_EXPECTED_COST:
        return result.mean
    if objective is Objective.MIN_P90_COST:
        return result.p90
    if objective is Objective.MAX_COMPLETION_UNDER_BUDGET:
        if budget is not None and _p_cost_le(result, budget) < 0.9:
            return float("inf")
        return -result.p_complete_from_sealed
    if objective is Objective.MIN_COST_FOR_TARGET_COMPLETION:
        if result.p_complete_from_sealed < confidence:
            return float("inf")
        return result.mean
    raise ValueError(f"unknown objective {objective!r}")


def _strategy_key(strategy: Strategy) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(strategy.units.items()))


def _k_max_for_product(
    product_id: int,
    boxes: dict[int, BoxSpec],
    pool: CardPool,
    params: CostParams,
    n_trials: int,
    seed: int,
    hard_cap: int = 20,
) -> int:
    """The quantity at which completion clears 99%, or a hard cap binds first."""
    k = 0
    while k < hard_cap:
        k += 1
        result = simulate(
            Strategy(units={product_id: k}), pool, boxes, params, n_trials=n_trials, seed=seed
        )
        if result.p_complete_from_sealed >= 0.99:
            break
    return k


def _grid_candidates(
    product_ids: list[int],
    boxes: dict[int, BoxSpec],
    pool: CardPool,
    params: CostParams,
    n_trials: int,
    seed: int,
) -> list[Strategy]:
    if not product_ids:
        return []
    if len(product_ids) == 1:
        pid = product_ids[0]
        k_max = _k_max_for_product(pid, boxes, pool, params, n_trials, seed)
        return [Strategy(units={pid: k}) for k in range(1, k_max + 1)]

    pid_a, pid_b = product_ids[0], product_ids[1]
    k_max_a = _k_max_for_product(pid_a, boxes, pool, params, n_trials, seed)
    k_max_b = _k_max_for_product(pid_b, boxes, pool, params, n_trials, seed)
    return [
        Strategy(units={k: v for k, v in ((pid_a, a), (pid_b, b)) if v > 0})
        for a in range(k_max_a + 1)
        for b in range(k_max_b + 1)
        if a > 0 or b > 0
    ]


def _greedy_candidates(
    product_ids: list[int],
    boxes: dict[int, BoxSpec],
    pool: CardPool,
    params: CostParams,
    n_trials: int,
    seed: int,
    objective: Objective,
    budget: float | None,
    confidence: float,
    max_rounds: int = 30,
) -> list[Strategy]:
    """Repeatedly add the unit with the best marginal objective improvement; stop when nothing
    improves. Followed by a +-1 local-search polish on the result."""
    current = Strategy()
    current_key = _objective_key(
        objective, simulate(current, pool, boxes, params, n_trials=n_trials, seed=seed), budget,
        confidence,
    )
    history = [Strategy(units=dict(current.units))]

    for _ in range(max_rounds):
        improved = False
        for pid in product_ids:
            trial_units = dict(current.units)
            trial_units[pid] = trial_units.get(pid, 0) + 1
            trial_strategy = Strategy(units=trial_units)
            result = simulate(trial_strategy, pool, boxes, params, n_trials=n_trials, seed=seed)
            key = _objective_key(objective, result, budget, confidence)
            if key < current_key:
                current_key = key
                current = trial_strategy
                improved = True
        history.append(Strategy(units=dict(current.units)))
        if not improved:
            break

    for pid in product_ids:
        for delta in (-1, 1):
            trial_units = dict(current.units)
            trial_units[pid] = max(0, trial_units.get(pid, 0) + delta)
            history.append(Strategy(units={k: v for k, v in trial_units.items() if v > 0}))
    return history


def search(
    objective: Objective,
    pool: CardPool,
    boxes: dict[int, BoxSpec],
    params: CostParams,
    n_trials: int = 20_000,
    seed: int = 0,
    budget: float | None = None,
    confidence: float = 0.9,
) -> list[tuple[Strategy, SimResult]]:
    """Return ranked (strategy, result), best first. Always includes the singles-only baseline.

    Two-phase precision: candidate generation and initial ranking run at a lower `n_trials`
    (<=5,000) for speed; the top few candidates (and the baseline) are re-simulated at the full
    requested `n_trials` before the final ranking is returned. This is a real precision
    trade-off, not a silent one -- coarse-phase noise could occasionally misorder two very close
    candidates before the refinement pass corrects it.
    """
    coarse_trials = min(n_trials, 5_000)
    product_ids = list(boxes.keys())

    candidates = [Strategy()]
    if len(product_ids) <= 2:
        candidates += _grid_candidates(product_ids, boxes, pool, params, coarse_trials, seed)
    else:
        candidates += _greedy_candidates(
            product_ids, boxes, pool, params, coarse_trials, seed, objective, budget, confidence
        )

    seen: set[tuple[tuple[int, int], ...]] = set()
    unique: list[Strategy] = []
    for s in candidates:
        key = _strategy_key(s)
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)

    coarse_results = [
        (s, simulate(s, pool, boxes, params, n_trials=coarse_trials, seed=seed)) for s in unique
    ]
    coarse_results.sort(key=lambda pair: _objective_key(objective, pair[1], budget, confidence))

    to_refine = {_strategy_key(Strategy()): Strategy()}
    for s, _ in coarse_results[:3]:
        to_refine[_strategy_key(s)] = s
    refined = {
        key: simulate(s, pool, boxes, params, n_trials=n_trials, seed=seed)
        for key, s in to_refine.items()
    }

    final = [
        (s, refined.get(_strategy_key(s), coarse_result))
        for s, coarse_result in coarse_results
    ]
    final.sort(key=lambda pair: _objective_key(objective, pair[1], budget, confidence))
    return final


def _top_chase_rarity_indices(pool: CardPool, boxes: dict[int, BoxSpec], n: int = 3) -> list[int]:
    """Top-n needed rarities by (price x count) among outcomes with probability < 1.0 -- i.e.
    actual chase slots, not guaranteed-1.0 commons/uncommons."""
    chase_rarity_indices: set[int] = set()
    for box in boxes.values():
        for slot in box.pack.slots:
            if len(slot.probabilities) > 1:
                chase_rarity_indices.update(int(i) for i in slot.rarity_indices)

    scored: list[tuple[float, int]] = []
    for rarity_idx in chase_rarity_indices:
        mask = pool.needed & (pool.rarity_index == rarity_idx)
        score = float(pool.prices[mask].sum())
        if score > 0:
            scored.append((score, rarity_idx))
    scored.sort(reverse=True)
    return [idx for _, idx in scored[:n]]


def _perturb_slot_probabilities(
    boxes: dict[int, BoxSpec], rarity_idx: int, factor: float
) -> dict[int, BoxSpec]:
    """Scale every outcome targeting `rarity_idx` by `factor`, renormalising the rest of that
    outcome's slot proportionally so probabilities still sum to 1.0."""
    perturbed: dict[int, BoxSpec] = {}
    for product_id, box in boxes.items():
        new_slots = []
        for slot in box.pack.slots:
            probs = slot.probabilities.copy()
            target_mask = slot.rarity_indices == rarity_idx
            if not target_mask.any():
                new_slots.append(slot)
                continue
            scaled = probs.copy()
            scaled[target_mask] *= factor
            other_mass = probs[~target_mask].sum()
            target_mass = scaled[target_mask].sum()
            if other_mass > 0:
                remaining = max(1.0 - target_mass, 0.0)
                scaled[~target_mask] = probs[~target_mask] / other_mass * remaining
            total = scaled.sum()
            if total > 0:
                scaled = scaled / total
            new_slots.append(replace(slot, probabilities=scaled))
        new_pack = replace(box.pack, slots=new_slots)
        perturbed[product_id] = replace(box, pack=new_pack)
    return perturbed


def _perturb_unit_price(boxes: dict[int, BoxSpec], factor: float) -> dict[int, BoxSpec]:
    return {pid: replace(box, unit_price=box.unit_price * factor) for pid, box in boxes.items()}


def sensitivity(
    strategy: Strategy,
    pool: CardPool,
    boxes: dict[int, BoxSpec],
    params: CostParams,
    n_trials: int = 20_000,
    seed: int = 0,
    baseline_strategy: Strategy | None = None,
) -> dict:
    """Tornado analysis. Ship this -- it is not optional.

    Perturbs: top-3 needed chase rarities' pull rates (+/-50%), `liquidation_rate` (0.5-0.85),
    and sealed unit price (+/-20%). Price-basis (low/market/high) perturbation needs alternate
    `CardPool.prices` arrays built from `get_current_prices`, which requires DB access this
    DB-oblivious module can't do itself -- deferred to the service layer that wires this into the
    UI (docs/06-roadmap.md's Phase 2 notes).

    Returns `{robust, baseline_mean, strategy_mean, factors: [{name, baseline_cost, low_cost,
    high_cost}]}`. `robust=False` if any perturbation flips which of (strategy, baseline) is
    cheaper -- the caller must surface this, not bury it in a number.
    """
    def _mean(s: Strategy, b: dict[int, BoxSpec], p: CostParams) -> float:
        return simulate(s, pool, b, p, n_trials=n_trials, seed=seed).mean

    baseline_strategy = baseline_strategy if baseline_strategy is not None else Strategy()
    base_mean = _mean(strategy, boxes, params)
    base_baseline_mean = _mean(baseline_strategy, boxes, params)
    base_favors_strategy = base_mean <= base_baseline_mean

    robust = True
    factors: list[dict] = []

    def _record(
        name: str, low: float, high: float, baseline_low: float, baseline_high: float
    ) -> None:
        nonlocal robust
        if (low <= baseline_low) != base_favors_strategy:
            robust = False
        if (high <= baseline_high) != base_favors_strategy:
            robust = False
        factors.append(
            {"name": name, "baseline_cost": base_mean, "low_cost": low, "high_cost": high}
        )

    for rarity_idx in _top_chase_rarity_indices(pool, boxes):
        low_boxes = _perturb_slot_probabilities(boxes, rarity_idx, 0.5)
        high_boxes = _perturb_slot_probabilities(boxes, rarity_idx, 1.5)
        _record(
            f"pull rate: {pool.rarities[rarity_idx]}",
            _mean(strategy, low_boxes, params),
            _mean(strategy, high_boxes, params),
            _mean(baseline_strategy, low_boxes, params),
            _mean(baseline_strategy, high_boxes, params),
        )

    low_params = replace(params, liquidation_rate=0.5)
    high_params = replace(params, liquidation_rate=0.85)
    _record(
        "liquidation_rate",
        _mean(strategy, boxes, low_params),
        _mean(strategy, boxes, high_params),
        _mean(baseline_strategy, boxes, low_params),
        _mean(baseline_strategy, boxes, high_params),
    )

    low_price_boxes = _perturb_unit_price(boxes, 0.8)
    high_price_boxes = _perturb_unit_price(boxes, 1.2)
    _record(
        "sealed unit price",
        _mean(strategy, low_price_boxes, params),
        _mean(strategy, high_price_boxes, params),
        base_baseline_mean,
        base_baseline_mean,
    )

    return {
        "robust": robust,
        "baseline_mean": base_baseline_mean,
        "strategy_mean": base_mean,
        "factors": factors,
    }
