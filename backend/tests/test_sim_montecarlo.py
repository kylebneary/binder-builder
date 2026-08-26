import numpy as np
import pytest
from app.sim.analytic import expected_remaining_singles_cost
from app.sim.montecarlo import draw_boxes, simulate
from app.sim.types import BoxSpec, CardPool, CostParams, PackSpec, SlotSpec, Strategy

RARITIES = ["Common", "Rare"]
VARIANTS = ["normal"]


def make_pool(entries: list[tuple[float, str, bool]]) -> CardPool:
    """entries: (price, rarity, needed) per pool index, all variant="normal"."""
    n = len(entries)
    return CardPool(
        variant_ids=np.arange(n, dtype=np.int64),
        prices=np.array([e[0] for e in entries], dtype=np.float64),
        resale=np.zeros(n, dtype=np.float64),
        rarity_index=np.array([RARITIES.index(e[1]) for e in entries], dtype=np.int32),
        variant_index=np.zeros(n, dtype=np.int32),
        needed=np.array([e[2] for e in entries], dtype=bool),
        rarities=RARITIES,
        variants=VARIANTS,
    )


def make_slot(label: str, repeat: int, rarity: str, probability: float = 1.0) -> SlotSpec:
    return SlotSpec(
        label=label,
        repeat=repeat,
        rarity_indices=np.array([RARITIES.index(rarity)], dtype=np.int32),
        probabilities=np.array([probability]),
        variants=["normal"],
    )


def make_box(slots: list[SlotSpec], packs_per_box: int, unit_price: float = 0.0) -> BoxSpec:
    pack = PackSpec(cards_per_pack=sum(s.repeat for s in slots), slots=slots)
    return BoxSpec(packs_per_box=packs_per_box, pack=pack, unit_price=unit_price)


# --- 1. Analytic agreement (no box_constraints) --------------------------------------------


def test_mc_mean_agrees_with_analytic_within_3_se():
    pool = make_pool([(1.0, "Common", True)] * 4 + [(10.0, "Rare", True)] * 2)
    common_slot = make_slot("common", 4, "Common")
    rare_slot = make_slot("rare", 1, "Rare")
    pack = PackSpec(cards_per_pack=5, slots=[common_slot, rare_slot])
    box = make_box([common_slot, rare_slot], packs_per_box=1)
    rng = np.random.default_rng(42)

    for k in (0, 1, 3, 8):
        pulled = draw_boxes(box, pool, n_boxes=k, n_trials=20_000, rng=rng)
        still_needed = pool.needed[None, :] & (pulled == 0)
        subtotal_per_trial = (still_needed * pool.prices[None, :]).sum(axis=1)
        mc_mean = subtotal_per_trial.mean()
        se = subtotal_per_trial.std(ddof=1) / np.sqrt(len(subtotal_per_trial))
        analytic_mean = expected_remaining_singles_cost(pool, pack, k_packs=k)
        assert abs(mc_mean - analytic_mean) <= max(3 * se, 1e-9)


# --- 2. Coupon-collector sanity --------------------------------------------------------------


def test_coupon_collector_expected_packs_to_complete():
    n = 8
    pool = make_pool([(1.0, "Common", True)] * n)
    slot = make_slot("single", 1, "Common")
    box = make_box([slot], packs_per_box=1)
    rng = np.random.default_rng(7)

    n_trials = 4000
    max_packs = 200
    pulled_total = np.zeros((n_trials, n), dtype=np.int32)
    completion_pack = np.full(n_trials, -1, dtype=np.int64)
    for k in range(1, max_packs + 1):
        pulled_total += draw_boxes(box, pool, n_boxes=1, n_trials=n_trials, rng=rng)
        newly_complete = (pulled_total > 0).all(axis=1) & (completion_pack == -1)
        completion_pack[newly_complete] = k
        if (completion_pack != -1).all():
            break

    assert (completion_pack != -1).all(), "not every trial completed within max_packs"
    mean_packs = completion_pack.mean()
    harmonic_n = sum(1.0 / i for i in range(1, n + 1))
    expected = n * harmonic_n
    assert abs(mean_packs - expected) / expected < 0.15


# --- 3. Degenerate cases ----------------------------------------------------------------------


def test_empty_need_list_gives_zero_cost():
    pool = make_pool([(5.0, "Rare", False), (5.0, "Rare", False)])
    slot = make_slot("rare", 1, "Rare")
    box = make_box([slot], packs_per_box=1)
    result = simulate(Strategy(), pool, {1: box}, CostParams(), n_trials=500, seed=0)
    assert result.mean == 0.0
    assert result.sd == 0.0
    assert result.p_complete_from_sealed == 1.0


def test_owning_nothing_buying_nothing_matches_plain_singles_sum():
    params = CostParams(shipping_per_order=1.29, cards_per_order=12)
    pool = make_pool([(1.0, "Common", True)] * 4 + [(10.0, "Rare", True)] * 2)
    slot = make_slot("rare", 1, "Rare")
    box = make_box([slot], packs_per_box=1)
    result = simulate(Strategy(), pool, {1: box}, params, n_trials=100, seed=0)

    subtotal = 4 * 1.0 + 2 * 10.0
    orders = np.ceil(6 / 12)
    shipping = orders * 1.29
    assert result.mean == pytest.approx(subtotal + shipping)
    assert result.sd == pytest.approx(0.0, abs=1e-9)


# --- 4. Determinism ----------------------------------------------------------------------------


def test_same_seed_gives_byte_identical_result():
    pool = make_pool([(1.0, "Common", True)] * 4 + [(10.0, "Rare", True)] * 2)
    common_slot = make_slot("common", 4, "Common")
    rare_slot = make_slot("rare", 1, "Rare")
    box = make_box([common_slot, rare_slot], packs_per_box=1, unit_price=20.0)
    strategy = Strategy(units={1: 2})

    r1 = simulate(strategy, pool, {1: box}, CostParams(), n_trials=1000, seed=123)
    r2 = simulate(strategy, pool, {1: box}, CostParams(), n_trials=1000, seed=123)

    assert r1.mean == r2.mean
    assert r1.sd == r2.sd
    assert r1.p10 == r2.p10 and r1.p90 == r2.p90
    assert r1.p_complete_from_sealed == r2.p_complete_from_sealed
    np.testing.assert_array_equal(r1.histogram[0], r2.histogram[0])
    np.testing.assert_array_equal(r1.histogram[1], r2.histogram[1])


# --- 5. Box constraints bite --------------------------------------------------------------------


def test_exact_per_box_guarantee_is_exact():
    # "Chase" is isolated -- no regular slot ever produces it -- so the guarantee is the only
    # source and the per-trial total must be exactly exact_per_box * n_boxes. Needs enough Chase
    # candidates that exact_per_box=4 isn't clipped down by too small a pool (min(target, pool
    # size) in _draw_box_guarantees).
    n_chase = 10
    pool = CardPool(
        variant_ids=np.arange(4 + n_chase, dtype=np.int64),
        prices=np.ones(4 + n_chase, dtype=np.float64),
        resale=np.zeros(4 + n_chase, dtype=np.float64),
        rarity_index=np.array([0, 0, 0, 0] + [1] * n_chase, dtype=np.int32),
        variant_index=np.zeros(4 + n_chase, dtype=np.int32),
        needed=np.zeros(4 + n_chase, dtype=bool),
        rarities=["Common", "Chase"],
        variants=["normal"],
    )
    common_slot = make_slot("common", 1, "Common")
    box = BoxSpec(
        packs_per_box=10,
        pack=PackSpec(cards_per_pack=1, slots=[common_slot]),
        guarantees={1: (4, 4)},  # rarity_index 1 == "Chase", exact_per_box=4
    )
    rng = np.random.default_rng(3)
    n_boxes = 2
    pulled = draw_boxes(box, pool, n_boxes=n_boxes, n_trials=500, rng=rng)
    chase_counts = pulled[:, 4:].sum(axis=1)
    assert np.all(chase_counts == 4 * n_boxes)


# --- 6. Monotonicity ------------------------------------------------------------------------


def test_expected_remaining_cost_is_non_increasing_in_k():
    pool = make_pool([(10.0, "Rare", True)] * 5)
    slot = make_slot("rare", 1, "Rare")
    box = make_box([slot], packs_per_box=1)
    rng = np.random.default_rng(99)

    means = []
    for k in range(6):
        pulled = draw_boxes(box, pool, n_boxes=k, n_trials=20_000, rng=rng)
        still_needed = pool.needed[None, :] & (pulled == 0)
        subtotal = (still_needed * pool.prices[None, :]).sum(axis=1)
        means.append(subtotal.mean())

    tolerance = 0.5  # generous slack for MC noise at 20k trials
    assert all(means[i + 1] <= means[i] + tolerance for i in range(len(means) - 1))


# --- Performance contract (docs/04-optimizer-spec.md: 100k trials / 36-pack box / ~200 cards --
#     in under 2 seconds). Skipped by default (see pyproject.toml's `-m "not slow"`); run with
#     `pytest -m slow backend/tests/test_sim_montecarlo.py`.


@pytest.mark.slow
def test_100k_trials_36_pack_box_200_cards_under_2_seconds():
    import time

    n_common, n_uncommon, n_rare = 120, 60, 20
    entries = (
        [(0.25, "Common", True)] * n_common
        + [(1.0, "Uncommon", True)] * n_uncommon
        + [(15.0, "Rare", True)] * n_rare
    )
    n = len(entries)
    pool = CardPool(
        variant_ids=np.arange(n, dtype=np.int64),
        prices=np.array([e[0] for e in entries], dtype=np.float64),
        resale=np.zeros(n, dtype=np.float64),
        rarity_index=np.array(
            [{"Common": 0, "Uncommon": 1, "Rare": 2}[e[1]] for e in entries], dtype=np.int32
        ),
        variant_index=np.zeros(n, dtype=np.int32),
        needed=np.array([e[2] for e in entries], dtype=bool),
        rarities=["Common", "Uncommon", "Rare"],
        variants=["normal"],
    )
    common_slot = SlotSpec(
        label="common",
        repeat=6,
        rarity_indices=np.array([0], dtype=np.int32),
        probabilities=np.array([1.0]),
        variants=["normal"],
    )
    uncommon_slot = SlotSpec(
        label="uncommon",
        repeat=3,
        rarity_indices=np.array([1], dtype=np.int32),
        probabilities=np.array([1.0]),
        variants=["normal"],
    )
    rare_slot = SlotSpec(
        label="rare",
        repeat=1,
        rarity_indices=np.array([2], dtype=np.int32),
        probabilities=np.array([1.0]),
        variants=["normal"],
    )
    box = BoxSpec(
        packs_per_box=36,
        pack=PackSpec(cards_per_pack=10, slots=[common_slot, uncommon_slot, rare_slot]),
        unit_price=100.0,
    )
    strategy = Strategy(units={1: 1})

    start = time.perf_counter()
    simulate(strategy, pool, {1: box}, CostParams(), n_trials=100_000, seed=0)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"simulate() took {elapsed:.2f}s, over the 2s budget"
