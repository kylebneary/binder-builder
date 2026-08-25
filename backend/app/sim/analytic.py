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
    """
    raise NotImplementedError  # TODO(phase-2.6)


def expected_remaining_singles_cost(pool: CardPool, pack: PackSpec, k_packs: int) -> float:
    """sum over needed cards of price * (1 - p)^k."""
    raise NotImplementedError  # TODO(phase-2.6)
