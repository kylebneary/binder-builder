"""Closed-form expected cost. Fast UI previews and, more importantly, a unit-test oracle.

Valid ONLY when box guarantees are absent -- it assumes packs are independent. See
docs/04-optimizer-spec.md for why that assumption fails on collated boxes.
"""
import numpy as np

from app.sim.types import CardPool, PackSpec


def per_pack_probability(pool: CardPool, pack: PackSpec) -> np.ndarray:
    """P(a given card appears in a given pack), one entry per pool index.

    Assumes uniform-within-rarity unless the profile narrows the pool. That is a modelling
    assumption and must be surfaced as one in the UI.

    A card's per-pack probability combines every slot outcome that can produce it: each outcome
    contributes an independent per-draw probability (outcome probability split evenly across the
    outcome's matching pool entries), applied once per `repeat` draw in that slot. Non-appearance
    across all contributing outcomes is multiplied, matching how e.g. a filler "Rare" outcome in a
    hit slot and a dedicated "rare" slot both bear on the same normal-variant Rare cards.
    """
    n = len(pool.variant_ids)
    prob_not_pulled = np.ones(n, dtype=np.float64)
    variant_lookup = {name: i for i, name in enumerate(pool.variants)}

    for slot in pack.slots:
        for rarity_idx, outcome_prob, variant in zip(
            slot.rarity_indices, slot.probabilities, slot.variants, strict=True
        ):
            variant_idx = variant_lookup.get(variant)
            if variant_idx is None:
                continue  # variant not present in this pool -- unsatisfiable outcome, not an error
            mask = (pool.rarity_index == rarity_idx) & (pool.variant_index == variant_idx)
            count = int(mask.sum())
            if count == 0:
                continue
            per_card = outcome_prob / count
            prob_not_pulled[mask] *= (1.0 - per_card) ** slot.repeat

    return 1.0 - prob_not_pulled


def expected_remaining_singles_cost(pool: CardPool, pack: PackSpec, k_packs: int) -> float:
    """sum over needed cards of price * (1 - p)^k."""
    p = per_pack_probability(pool, pack)
    prob_never_pulled = (1.0 - p) ** k_packs
    contributions = np.where(pool.needed, pool.prices * prob_never_pulled, 0.0)
    return float(contributions.sum())
