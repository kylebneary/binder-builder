"""Vectorised Monte Carlo engine. The primary source of truth.

PERFORMANCE CONTRACT: 100,000 trials of a 36-pack box over a ~200-card set in under 2 seconds.
That is only reachable by drawing all trials at once against integer card indices. A per-pack
Python loop is roughly 100x too slow and will make the UI unusable -- design for NumPy from
the first line rather than optimising later.
"""
import numpy as np

from app.sim.types import BoxSpec, CardPool, CostParams, SimResult, Strategy


def draw_boxes(
    box: BoxSpec, pool: CardPool, n_boxes: int, n_trials: int, rng: np.random.Generator
) -> np.ndarray:
    """Return a (n_trials, n_pool) int16 count matrix of cards pulled.

    Order of operations matters:
      1. draw guaranteed hits per box WITHOUT replacement from their rarity pool
      2. assign them to distinct packs
      3. fill remaining slots from the renormalised slot distributions
    """
    raise NotImplementedError  # TODO(phase-2.7)


def singles_cost(needed_mask: np.ndarray, pool: CardPool, params: CostParams) -> np.ndarray:
    """Vectorised over trials. Includes the seller-consolidation shipping model."""
    raise NotImplementedError  # TODO(phase-2.7)


def liquidation_value(dupes: np.ndarray, pool: CardPool, params: CostParams) -> np.ndarray:
    """Duplicates net resale, floored at zero below params.resale_floor."""
    raise NotImplementedError  # TODO(phase-2.7)


def simulate(
    strategy: Strategy,
    pool: CardPool,
    boxes: dict[int, BoxSpec],
    params: CostParams,
    n_trials: int = 20_000,
    seed: int = 0,
) -> SimResult:
    """NetCost = SealedCost + SinglesCost(remaining) - Liquidation(dupes)."""
    raise NotImplementedError  # TODO(phase-2.7)
