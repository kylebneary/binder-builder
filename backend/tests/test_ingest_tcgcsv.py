import json
from datetime import date
from pathlib import Path

import respx
from app.ingest.tcgcsv import TcgCsvClient, TcgCsvPriceSource
from httpx import Response

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://tcgcsv.test"
GROUP_ID = 23651


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_group(respx_mock):
    respx_mock.get(f"{BASE_URL}/tcgplayer/3/groups").mock(
        return_value=Response(200, json=_load("tcgcsv_groups.json"))
    )
    respx_mock.get(f"{BASE_URL}/tcgplayer/3/{GROUP_ID}/products").mock(
        return_value=Response(200, json=_load("tcgcsv_products_23651.json"))
    )
    respx_mock.get(f"{BASE_URL}/tcgplayer/3/{GROUP_ID}/prices").mock(
        return_value=Response(200, json=_load("tcgcsv_prices_23651.json"))
    )


@respx.mock
def test_fetch_groups_returns_trimmed_real_data():
    _mock_group(respx.mock)
    client = TcgCsvClient(base_url=BASE_URL, category_id=3)
    groups = client.fetch_groups()
    names = {g["name"] for g in groups}
    assert "SV08: Surging Sparks" in names
    assert any(g["groupId"] == GROUP_ID for g in groups)


@respx.mock
def test_fetch_products_classifies_sealed_vs_singles():
    _mock_group(respx.mock)
    client = TcgCsvClient(base_url=BASE_URL, category_id=3)
    products = list(client.fetch_products(GROUP_ID))
    assert len(products) == 6

    singles = [p for p in products if not p.is_sealed]
    sealed = [p for p in products if p.is_sealed]
    assert len(singles) == 4
    assert len(sealed) == 2

    diglett = next(p for p in singles if p.tcgplayer_product_id == 589855)
    assert diglett.card_number == "122/191"
    assert diglett.rarity == "Common"

    bnb_box = next(p for p in sealed if p.tcgplayer_product_id == 565599)
    assert bnb_box.card_number is None
    assert bnb_box.rarity is None


@respx.mock
def test_fetch_group_prices_parses_multi_subtype_rows():
    _mock_group(respx.mock)
    client = TcgCsvClient(base_url=BASE_URL, category_id=3)
    prices = list(client.fetch_group_prices(GROUP_ID, date(2026, 8, 25)))
    assert len(prices) == 8

    diglett_prices = [p for p in prices if p.tcgplayer_product_id == 589855]
    sub_types = {p.sub_type_name for p in diglett_prices}
    assert sub_types == {"Normal", "Reverse Holofoil"}
    for p in diglett_prices:
        assert p.observed_on == date(2026, 8, 25)
        assert p.source == "tcgcsv"
        assert p.market is not None


@respx.mock
def test_price_source_fetch_prices_filters_to_given_groups():
    _mock_group(respx.mock)
    source = TcgCsvPriceSource(client=TcgCsvClient(base_url=BASE_URL, category_id=3))
    prices = list(source.fetch_prices(date(2026, 8, 25), group_ids=[GROUP_ID]))
    assert len(prices) == 8
    assert {p.tcgplayer_product_id for p in prices} == {
        589855,
        589856,
        589857,
        565599,
        565602,
        589858,
    }
