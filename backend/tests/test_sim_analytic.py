import numpy as np
import pytest
from app.sim.analytic import expected_remaining_singles_cost, per_pack_probability
from app.sim.types import CardPool, PackSpec, SlotSpec

RARITIES = ["Common", "Rare"]
VARIANTS = ["normal", "reverse_holofoil"]


def make_pool(entries: list[tuple[float, str, str, bool]]) -> CardPool:
    """entries: (price, rarity, variant, needed) per pool index."""
    n = len(entries)
    return CardPool(
        variant_ids=np.arange(n, dtype=np.int64),
        prices=np.array([e[0] for e in entries], dtype=np.float64),
        resale=np.zeros(n, dtype=np.float64),
        rarity_index=np.array([RARITIES.index(e[1]) for e in entries], dtype=np.int32),
        variant_index=np.array([VARIANTS.index(e[2]) for e in entries], dtype=np.int32),
        needed=np.array([e[3] for e in entries], dtype=bool),
        rarities=RARITIES,
        variants=VARIANTS,
    )


def make_pack(slots: list[SlotSpec]) -> PackSpec:
    return PackSpec(cards_per_pack=sum(s.repeat for s in slots), slots=slots)


def test_per_pack_probability_single_slot_uniform():
    pool = make_pool([(1.0, "Common", "normal", True)] * 4)
    pack = make_pack(
        [
            SlotSpec(
                label="common",
                repeat=4,
                rarity_indices=np.array([0], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            )
        ]
    )
    p = per_pack_probability(pool, pack)
    expected = 1.0 - (1.0 - 1.0 / 4) ** 4
    assert p == pytest.approx(np.full(4, expected))


def test_per_pack_probability_combines_multiple_slots():
    pool = make_pool(
        [(1.0, "Common", "normal", True)] * 4 + [(10.0, "Rare", "normal", True)] * 2
    )
    pack = make_pack(
        [
            SlotSpec(
                label="common",
                repeat=4,
                rarity_indices=np.array([0], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            ),
            SlotSpec(
                label="rare",
                repeat=1,
                rarity_indices=np.array([1], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            ),
        ]
    )
    p = per_pack_probability(pool, pack)
    assert p[:4] == pytest.approx(np.full(4, 1.0 - 0.75**4))
    assert p[4:] == pytest.approx(np.full(2, 0.5))


def test_per_pack_probability_respects_variant():
    pool = make_pool(
        [(5.0, "Rare", "normal", True), (5.0, "Rare", "reverse_holofoil", True)]
    )
    pack = make_pack(
        [
            SlotSpec(
                label="rare",
                repeat=1,
                rarity_indices=np.array([1], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            )
        ]
    )
    p = per_pack_probability(pool, pack)
    assert p[0] == pytest.approx(1.0)
    assert p[1] == 0.0


def test_per_pack_probability_missing_variant_in_pool_is_zero_not_error():
    pool = make_pool([(5.0, "Rare", "normal", True)])
    pack = make_pack(
        [
            SlotSpec(
                label="reverse_holo",
                repeat=1,
                rarity_indices=np.array([1], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["reverse_holofoil"],
            )
        ]
    )
    p = per_pack_probability(pool, pack)
    assert p == pytest.approx(np.zeros(1))


def test_expected_remaining_singles_cost_matches_hand_calc():
    pool = make_pool(
        [(1.0, "Common", "normal", True)] * 4 + [(10.0, "Rare", "normal", True)] * 2
    )
    pack = make_pack(
        [
            SlotSpec(
                label="common",
                repeat=4,
                rarity_indices=np.array([0], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            ),
            SlotSpec(
                label="rare",
                repeat=1,
                rarity_indices=np.array([1], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            ),
        ]
    )
    cost = expected_remaining_singles_cost(pool, pack, k_packs=1)
    assert cost == pytest.approx(11.265625)


def test_expected_remaining_singles_cost_k_zero_equals_full_needed_sum():
    pool = make_pool(
        [(1.0, "Common", "normal", True)] * 4 + [(10.0, "Rare", "normal", True)] * 2
    )
    pack = make_pack(
        [
            SlotSpec(
                label="rare",
                repeat=1,
                rarity_indices=np.array([1], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            )
        ]
    )
    cost = expected_remaining_singles_cost(pool, pack, k_packs=0)
    assert cost == pytest.approx(4 * 1.0 + 2 * 10.0)


def test_expected_remaining_singles_cost_excludes_not_needed():
    pool = make_pool([(10.0, "Rare", "normal", False), (10.0, "Rare", "normal", True)])
    pack = make_pack(
        [
            SlotSpec(
                label="rare",
                repeat=1,
                rarity_indices=np.array([1], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            )
        ]
    )
    cost = expected_remaining_singles_cost(pool, pack, k_packs=0)
    assert cost == pytest.approx(10.0)  # only the needed card counts


def test_expected_remaining_singles_cost_monotonic_non_increasing_in_k():
    pool = make_pool([(10.0, "Rare", "normal", True)] * 5)
    pack = make_pack(
        [
            SlotSpec(
                label="rare",
                repeat=1,
                rarity_indices=np.array([1], dtype=np.int32),
                probabilities=np.array([1.0]),
                variants=["normal"],
            )
        ]
    )
    costs = [expected_remaining_singles_cost(pool, pack, k_packs=k) for k in range(6)]
    assert all(costs[i] >= costs[i + 1] for i in range(len(costs) - 1))
