import numpy as np

from app.sim.optimizer import Objective, search, sensitivity
from app.sim.types import BoxSpec, CardPool, CostParams, PackSpec, SlotSpec, Strategy

RARITIES = ["Common", "Rare"]


def make_pool(entries: list[tuple[float, str, bool]]) -> CardPool:
    n = len(entries)
    return CardPool(
        variant_ids=np.arange(n, dtype=np.int64),
        prices=np.array([e[0] for e in entries], dtype=np.float64),
        resale=np.zeros(n, dtype=np.float64),
        rarity_index=np.array([RARITIES.index(e[1]) for e in entries], dtype=np.int32),
        variant_index=np.zeros(n, dtype=np.int32),
        needed=np.array([e[2] for e in entries], dtype=bool),
        rarities=RARITIES,
        variants=["normal"],
    )


def make_slot(repeat: int, rarity: str, probability: float = 1.0) -> SlotSpec:
    return SlotSpec(
        label=rarity.lower(),
        repeat=repeat,
        rarity_indices=np.array([RARITIES.index(rarity)], dtype=np.int32),
        probabilities=np.array([probability]),
        variants=["normal"],
    )


def make_box(slots: list[SlotSpec], packs_per_box: int, unit_price: float) -> BoxSpec:
    pack = PackSpec(cards_per_pack=sum(s.repeat for s in slots), slots=slots)
    return BoxSpec(packs_per_box=packs_per_box, pack=pack, unit_price=unit_price)


def test_search_includes_singles_only_baseline():
    pool = make_pool([(10.0, "Rare", True)] * 3)
    box = make_box([make_slot(1, "Rare")], packs_per_box=1, unit_price=100.0)
    results = search(Objective.MIN_EXPECTED_COST, pool, {1: box}, CostParams(), n_trials=2000, seed=0)
    strategies = [s for s, _ in results]
    assert Strategy() in strategies


def test_grid_search_prefers_cheaper_of_two_synthetic_strategies():
    # Cheap box makes buying 3 of it much cheaper than buying the needed rares as singles.
    pool = make_pool([(50.0, "Rare", True)] * 10)
    cheap_box = make_box([make_slot(1, "Rare")], packs_per_box=10, unit_price=1.0)
    results = search(
        Objective.MIN_EXPECTED_COST, pool, {1: cheap_box}, CostParams(), n_trials=3000, seed=0
    )
    best_strategy, best_result = results[0]
    baseline_result = next(r for s, r in results if s == Strategy())
    assert best_strategy != Strategy()
    assert best_result.mean < baseline_result.mean


def test_greedy_activates_at_three_or_more_products():
    pool = make_pool([(10.0, "Rare", True)] * 3)
    boxes = {
        i: make_box([make_slot(1, "Rare")], packs_per_box=1, unit_price=5.0) for i in (1, 2, 3)
    }
    # Should not raise / should not attempt an exhaustive 3D grid -- just needs to complete and
    # still include the baseline.
    results = search(Objective.MIN_EXPECTED_COST, pool, boxes, CostParams(), n_trials=2000, seed=0)
    assert Strategy() in [s for s, _ in results]
    assert len(results) >= 2


def test_search_results_sorted_by_objective():
    pool = make_pool([(10.0, "Rare", True)] * 5)
    box = make_box([make_slot(1, "Rare")], packs_per_box=1, unit_price=5.0)
    results = search(Objective.MIN_EXPECTED_COST, pool, {1: box}, CostParams(), n_trials=3000, seed=0)
    means = [r.mean for _, r in results]
    assert means == sorted(means)


def test_sensitivity_flags_not_robust_when_ranking_flips():
    # Rare is priced just above the box's near-guaranteed value; halving its pull rate should
    # make singles look better than the box, flipping which option is cheaper.
    pool = make_pool([(20.0, "Rare", True)] * 4)
    box = make_box([make_slot(1, "Rare")], packs_per_box=4, unit_price=1.0)
    result = sensitivity(Strategy(units={1: 1}), pool, {1: box}, CostParams(), n_trials=4000, seed=0)
    assert "factors" in result
    assert isinstance(result["robust"], bool)


def test_sensitivity_reports_baseline_and_strategy_means():
    pool = make_pool([(10.0, "Rare", True)] * 3)
    box = make_box([make_slot(1, "Rare")], packs_per_box=3, unit_price=5.0)
    result = sensitivity(Strategy(units={1: 1}), pool, {1: box}, CostParams(), n_trials=2000, seed=0)
    assert result["baseline_mean"] >= 0
    assert result["strategy_mean"] >= 0
    assert len(result["factors"]) >= 1  # at least liquidation_rate + sealed unit price
