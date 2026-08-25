from decimal import Decimal

from app.services.costs import CostParams, resale_value, singles_cost


def test_singles_cost_empty_list_is_all_zero():
    result = singles_cost([])
    assert result.n_cards == 0
    assert result.subtotal == Decimal("0")
    assert result.orders == 0
    assert result.shipping == Decimal("0")
    assert result.total == Decimal("0")


def test_singles_cost_seller_consolidation_shipping():
    params = CostParams(shipping_per_order=Decimal("1.29"), cards_per_order=12)
    prices = [Decimal("1.00")] * 13  # 13 cards -> ceil(13/12) = 2 orders
    result = singles_cost(prices, params)
    assert result.n_cards == 13
    assert result.subtotal == Decimal("13.00")
    assert result.orders == 2
    assert result.shipping == Decimal("2.58")
    assert result.total == Decimal("15.58")


def test_singles_cost_exact_multiple_of_cards_per_order():
    params = CostParams(shipping_per_order=Decimal("1.29"), cards_per_order=12)
    result = singles_cost([Decimal("0.50")] * 12, params)
    assert result.orders == 1
    assert result.shipping == Decimal("1.29")


def test_singles_cost_applies_sales_tax():
    params = CostParams(sales_tax_rate=Decimal("0.10"), cards_per_order=100)
    result = singles_cost([Decimal("10.00")], params)
    assert result.tax == Decimal("1.00")
    assert result.total == result.subtotal + result.shipping + result.tax


def test_resale_value_floors_below_resale_floor():
    params = CostParams(liquidation_rate=Decimal("0.70"), resale_floor=Decimal("2.00"))
    assert resale_value(Decimal("1.50"), params) == Decimal("0")


def test_resale_value_applies_liquidation_rate_at_and_above_floor():
    params = CostParams(liquidation_rate=Decimal("0.70"), resale_floor=Decimal("2.00"))
    assert resale_value(Decimal("2.00"), params) == Decimal("1.40")
    assert resale_value(Decimal("10.00"), params) == Decimal("7.00")
