"""Strategy search over sealed-product quantities.

The objective is a simulation output and is not linear -- do not reach for an MIP solver.
Grid search for <=2 product types (typically <400 simulations); greedy marginal analysis beyond.
Always evaluate and report the singles-only baseline alongside the winner.
"""
from enum import StrEnum

from app.sim.types import CostParams, Strategy


class Objective(StrEnum):
    MIN_EXPECTED_COST = "min_expected_cost"
    MIN_P90_COST = "min_p90_cost"
    MAX_COMPLETION_UNDER_BUDGET = "max_completion_under_budget"
    MIN_COST_FOR_TARGET_COMPLETION = "min_cost_for_target_completion"


def search(objective: Objective, params: CostParams, **kwargs) -> list[tuple[Strategy, float]]:
    """Return ranked (strategy, objective value), best first."""
    raise NotImplementedError  # TODO(phase-2.10)


def sensitivity(strategy: Strategy, params: CostParams, **kwargs) -> dict:
    """Tornado analysis. Ship this -- it is not optional.

    Perturb: top-3 cost-driving rarity pull rates (+/-50%), liquidation_rate (0.5-0.85),
    pack price (+/-20%), price basis (low/market/high). If the recommendation flips under a
    plausible pull-rate perturbation, the caller must tell the user it is not robust.
    """
    raise NotImplementedError  # TODO(phase-2.14)
