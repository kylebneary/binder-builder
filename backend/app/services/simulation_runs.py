"""Caching + persistence for simulation runs (docs/02-data-model.md's `simulation_run` table).

Cache key = (goal, strategy, params, n_trials, seed, price_date, profile_version), per
docs/04-optimizer-spec.md's "Cache aggressively... hash that tuple and memoise" -- one row per
evaluated strategy point, not one row per search invocation, so re-running a search that revisits
an already-evaluated (strategy, params, price date) combination is free.
"""
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Goal, PricePoint, PullRateProfile, SealedProduct, SimulationRun
from app.services.collection import get_or_create_default_collection
from app.services.simulate import (
    build_box_spec,
    build_card_pool,
    resolve_pull_rate_profile,
    sealed_unit_price,
)
from app.sim.montecarlo import simulate
from app.sim.optimizer import Objective, search
from app.sim.types import BoxSpec, CardPool, CostParams, SimResult, Strategy


def _cost_params_dict(params: CostParams) -> dict:
    return asdict(params)


def compute_cache_key(
    goal_id: int,
    strategy: Strategy,
    params: CostParams,
    n_trials: int,
    seed: int,
    price_date: str,
    profile_version: str,
) -> str:
    payload = {
        "goal_id": goal_id,
        "strategy": dict(sorted(strategy.units.items())),
        "params": _cost_params_dict(params),
        "n_trials": n_trials,
        "seed": seed,
        "price_date": price_date,
        "profile_version": profile_version,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _sim_result_dict(result: SimResult) -> dict:
    counts, edges = result.histogram
    return {
        "mean": result.mean,
        "sd": result.sd,
        "p10": result.p10,
        "p50": result.p50,
        "p90": result.p90,
        "p95": result.p95,
        "p_complete_from_sealed": result.p_complete_from_sealed,
        "expected_cards_remaining": result.expected_cards_remaining,
        "histogram_counts": counts.tolist(),
        "histogram_edges": edges.tolist(),
        "n_trials": result.n_trials,
        "seed": result.seed,
    }


def _latest_price_date(db: Session) -> str:
    """The daily price job ingests the whole catalogue in one batch (CLAUDE.md), so the global
    max `observed_on` is a fair proxy for "today's price snapshot date" -- falls back to today
    if the DB has no prices at all, so staleness is never silently invisible."""
    result = db.execute(select(func.max(PricePoint.observed_on))).scalar_one_or_none()
    return result.isoformat() if result else date.today().isoformat()


def _load_primary_profile(db: Session, set_id: int) -> PullRateProfile | None:
    return db.execute(
        select(PullRateProfile).where(
            PullRateProfile.set_id == set_id, PullRateProfile.is_default.is_(True)
        )
    ).scalars().first()


def _resolve_boxes(
    db: Session,
    set_id: int,
    primary_profile: PullRateProfile,
    pool: CardPool,
    sealed_product_ids: set[int] | None = None,
) -> tuple[dict[int, BoxSpec], list[dict]]:
    """Every sealed product for the set (optionally filtered) that resolves to a usable
    `BoxSpec`, plus a reported reason for every one that doesn't -- never silently dropped.

    Only sealed products resolving to the SAME profile as the goal's set default are included:
    `pool`'s rarity/variant vocabulary is scoped to one profile, so a hypothetical sealed product
    using a different profile can't share it. No real set has more than one profile today.
    """
    stmt = select(SealedProduct).where(SealedProduct.set_id == set_id)
    if sealed_product_ids is not None:
        stmt = stmt.where(SealedProduct.id.in_(sealed_product_ids))
    products = db.execute(stmt).scalars().all()

    boxes: dict[int, BoxSpec] = {}
    unsimulatable: list[dict] = []
    for p in products:
        resolved_profile = resolve_pull_rate_profile(db, p)
        if resolved_profile is None:
            unsimulatable.append(
                {"sealed_product_id": p.id, "name": p.name, "reason": "no pull-rate profile"}
            )
            continue
        if resolved_profile.id != primary_profile.id:
            unsimulatable.append(
                {
                    "sealed_product_id": p.id,
                    "name": p.name,
                    "reason": "uses a different pull-rate profile than this goal's set default",
                }
            )
            continue
        price = sealed_unit_price(db, p)
        box = build_box_spec(db, p, pool, price)
        if box is None:
            unsimulatable.append(
                {"sealed_product_id": p.id, "name": p.name, "reason": "no packs_per_unit"}
            )
            continue
        boxes[p.id] = box
    return boxes, unsimulatable


def _get_or_store(
    db: Session,
    goal_id: int,
    strategy: Strategy,
    params: CostParams,
    n_trials: int,
    seed: int,
    price_date: str,
    profile_version: str,
    result: SimResult,
) -> SimulationRun:
    cache_key = compute_cache_key(
        goal_id, strategy, params, n_trials, seed, price_date, profile_version
    )
    existing = db.execute(
        select(SimulationRun).where(SimulationRun.cache_key == cache_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    run = SimulationRun(
        goal_id=goal_id,
        params_json=_cost_params_dict(params),
        strategy_json=dict(sorted(strategy.units.items())),
        n_trials=n_trials,
        seed=seed,
        price_date=price_date,
        profile_version=profile_version,
        engine_version="0.1.0",
        cache_key=cache_key,
        results_json=_sim_result_dict(result),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_and_cache(
    db: Session,
    goal_id: int,
    strategy: Strategy,
    params: CostParams,
    n_trials: int = 20_000,
    seed: int = 0,
) -> SimulationRun:
    goal = db.get(Goal, goal_id)
    if goal is None or goal.set_id is None:
        raise ValueError(f"Goal {goal_id} not found or has no set")
    profile = _load_primary_profile(db, goal.set_id)
    if profile is None:
        raise ValueError(f"No pull-rate profile for set {goal.set_id}")

    collection = get_or_create_default_collection(db)
    pool_result = build_card_pool(db, goal.set_id, profile, goal_id, collection.id)
    boxes, _unsimulatable = _resolve_boxes(
        db, goal.set_id, profile, pool_result.pool, set(strategy.units.keys()) or None
    )
    result = simulate(strategy, pool_result.pool, boxes, params, n_trials=n_trials, seed=seed)

    price_date = _latest_price_date(db)
    profile_version = f"{profile.id}:{profile.updated_at.isoformat()}"
    return _get_or_store(
        db, goal_id, strategy, params, n_trials, seed, price_date, profile_version, result
    )


@dataclass(slots=True)
class SearchAndCacheResult:
    runs: list[SimulationRun] = field(default_factory=list)
    unsimulatable: list[dict] = field(default_factory=list)
    uncovered_needed_price_sum: Decimal = Decimal("0")


def run_search_and_cache(
    db: Session,
    goal_id: int,
    objective: Objective,
    params: CostParams,
    n_trials: int = 20_000,
    seed: int = 0,
    sealed_product_ids: set[int] | None = None,
) -> SearchAndCacheResult:
    goal = db.get(Goal, goal_id)
    if goal is None or goal.set_id is None:
        raise ValueError(f"Goal {goal_id} not found or has no set")
    profile = _load_primary_profile(db, goal.set_id)
    if profile is None:
        raise ValueError(f"No pull-rate profile for set {goal.set_id}")

    collection = get_or_create_default_collection(db)
    pool_result = build_card_pool(db, goal.set_id, profile, goal_id, collection.id)
    boxes, unsimulatable = _resolve_boxes(
        db, goal.set_id, profile, pool_result.pool, sealed_product_ids
    )

    ranked = search(objective, pool_result.pool, boxes, params, n_trials=n_trials, seed=seed)

    price_date = _latest_price_date(db)
    profile_version = f"{profile.id}:{profile.updated_at.isoformat()}"
    runs = [
        _get_or_store(
            db, goal_id, strategy, params, n_trials, seed, price_date, profile_version, result
        )
        for strategy, result in ranked
    ]
    return SearchAndCacheResult(
        runs=runs,
        unsimulatable=unsimulatable,
        uncovered_needed_price_sum=pool_result.uncovered_needed_price_sum,
    )
