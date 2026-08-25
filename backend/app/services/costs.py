"""Shipping and liquidation cost models -- docs/04-optimizer-spec.md 'Cost model'.

Money stays Decimal here (CLAUDE.md: never float for currency). The vectorised simulator gets
its own float/NumPy version at its own boundary later (see app/sim/montecarlo.py) -- this module
is the plain, deterministic version used directly by the need-list view.
"""
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class CostParams:
    shipping_per_order: Decimal = Decimal("1.29")
    cards_per_order: int = 12
    sales_tax_rate: Decimal = Decimal("0")
    liquidation_rate: Decimal = Decimal("0.70")
    resale_floor: Decimal = Decimal("2.00")
    bulk_threshold: Decimal = Decimal("0.35")
    bulk_lot_price: Decimal | None = None


@dataclass(slots=True)
class SinglesCostBreakdown:
    n_cards: int
    subtotal: Decimal
    orders: int
    shipping: Decimal
    tax: Decimal
    total: Decimal


def singles_cost(prices: list[Decimal], params: CostParams | None = None) -> SinglesCostBreakdown:
    """SinglesCost(N') = sum(p_single(v)) + ShippingCost(|N'|), with the seller-consolidation
    shipping model: orders = ceil(n / cards_per_order), shipping = orders * shipping_per_order.
    """
    params = params or CostParams()
    n = len(prices)
    if n == 0:
        return SinglesCostBreakdown(0, Decimal("0"), 0, Decimal("0"), Decimal("0"), Decimal("0"))

    subtotal = sum(prices, Decimal("0"))
    orders = math.ceil(n / params.cards_per_order)
    shipping = params.shipping_per_order * orders
    tax = subtotal * params.sales_tax_rate
    total = subtotal + shipping + tax
    return SinglesCostBreakdown(
        n_cards=n,
        subtotal=_cents(subtotal),
        orders=orders,
        shipping=_cents(shipping),
        tax=_cents(tax),
        total=_cents(total),
    )


def resale_value(price: Decimal, params: CostParams | None = None) -> Decimal:
    """p_resale(v) = price * liquidation_rate if price >= resale_floor, else 0 -- a duplicate
    below the floor is bulk and realistically nets nothing."""
    params = params or CostParams()
    if price < params.resale_floor:
        return Decimal("0")
    return _cents(price * params.liquidation_rate)
