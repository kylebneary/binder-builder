"""Plain dataclasses at the sim boundary.

The simulator must never touch the ORM or a DB session -- it runs hundreds of thousands of
trials and cannot afford a lazy load. The service layer loads everything into these once.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class CardPool:
    """Flattened, index-addressed view of a set. All arrays are parallel and same-length."""

    variant_ids: np.ndarray      # int64, card_variant.id
    prices: np.ndarray           # float64, acquisition price
    resale: np.ndarray           # float64, expected net resale
    rarity_index: np.ndarray     # int32, index into `rarities`
    variant_index: np.ndarray    # int32, index into `variants` (normal/holofoil/reverse_holo/...)
    needed: np.ndarray           # bool, part of goal and not owned
    rarities: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)

    def indices_for_rarity(self, rarity: str) -> np.ndarray:
        return np.flatnonzero(self.rarity_index == self.rarities.index(rarity))

    def indices_for(self, rarity: str, variant: str) -> np.ndarray:
        """Pool indices matching both rarity and variant. Empty (not an error) if either is
        absent from this pool -- e.g. the known SWSH Rare Ultra/Rainbow/Secret zero-variant gap
        (see docs/07-data-backlog.md), where a slot_outcome references a (rarity, variant) combo
        that has no priced card_variant rows at all.
        """
        if rarity not in self.rarities or variant not in self.variants:
            return np.empty(0, dtype=np.int64)
        return np.flatnonzero(
            (self.rarity_index == self.rarities.index(rarity))
            & (self.variant_index == self.variants.index(variant))
        )


@dataclass(slots=True)
class SlotSpec:
    label: str
    repeat: int
    rarity_indices: np.ndarray   # int32, one per outcome
    probabilities: np.ndarray    # float64, sums to 1.0
    variants: list[str]


@dataclass(slots=True)
class PackSpec:
    cards_per_pack: int
    slots: list[SlotSpec]


@dataclass(slots=True)
class BoxSpec:
    packs_per_box: int
    pack: PackSpec
    unit_price: float = 0.0
    # rarity_index -> (min, max) guaranteed per box. This is what forces Monte Carlo.
    guarantees: dict[int, tuple[int, int]] = field(default_factory=dict)


@dataclass(slots=True)
class CostParams:
    shipping_per_order: float = 1.29
    cards_per_order: int = 12
    sealed_shipping: float = 0.0
    sales_tax_rate: float = 0.0
    liquidation_rate: float = 0.70
    resale_floor: float = 2.00
    bulk_threshold: float = 0.35
    bulk_lot_price: float | None = None
    price_basis: str = "market"   # "market" | "low" | blended


@dataclass(slots=True)
class Strategy:
    """How many of each sealed product to buy. Empty == singles-only baseline."""

    units: dict[int, int] = field(default_factory=dict)   # sealed_product_id -> qty


@dataclass(slots=True)
class SimResult:
    mean: float
    sd: float
    p10: float
    p50: float
    p90: float
    p95: float
    p_complete_from_sealed: float
    expected_cards_remaining: float
    histogram: tuple[np.ndarray, np.ndarray]
    n_trials: int
    seed: int
