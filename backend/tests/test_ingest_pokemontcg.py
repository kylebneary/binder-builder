import json
from pathlib import Path

import respx
from app.ingest.pokemontcg import PokemonTcgCardSource, PokemonTcgClient
from httpx import Response

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://api.pokemontcg.io/v2"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
def test_fetch_sets_maps_documented_schema():
    respx.get(f"{BASE_URL}/sets").mock(
        return_value=Response(200, json=_load("pokemontcg_sets.json"))
    )
    source = PokemonTcgCardSource(client=PokemonTcgClient(base_url=BASE_URL))
    sets = list(source.fetch_sets())

    assert [s.ptcg_set_id for s in sets] == ["sv8", "sv7"]
    sv8 = sets[0]
    assert sv8.name == "Surging Sparks"
    assert sv8.series == "Scarlet & Violet"
    assert sv8.printed_total == 191
    assert sv8.total == 252
    assert sv8.release_date.isoformat() == "2024-11-08"
    assert sv8.ptcgo_code == "SSP"
    assert sv8.symbol_url.endswith("symbol.png")
    assert sv8.logo_url.endswith("logo.png")


@respx.mock
def test_fetch_cards_maps_documented_schema():
    respx.get(f"{BASE_URL}/cards").mock(
        return_value=Response(200, json=_load("pokemontcg_cards_sv8.json"))
    )
    source = PokemonTcgCardSource(client=PokemonTcgClient(base_url=BASE_URL))
    cards = list(source.fetch_cards("sv8"))

    assert len(cards) == 3
    diglett = next(c for c in cards if c.ptcg_card_id == "sv8-122")
    assert diglett.ptcg_set_id == "sv8"
    assert diglett.number == "122"
    assert diglett.name == "Alolan Diglett"
    assert diglett.rarity == "Common"
    assert diglett.supertype == "Pokémon"
    assert diglett.subtypes == ["Basic"]
    assert diglett.types == ["Metal"]
    assert diglett.national_pokedex_numbers == [50]
    assert diglett.image_small.endswith("122.png")


@respx.mock
def test_fetch_paginates_until_short_page(monkeypatch):
    import app.ingest.pokemontcg as mod

    monkeypatch.setattr(mod, "PAGE_SIZE", 2)
    page1 = {"data": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]}
    page2 = {"data": [{"id": "c", "name": "C"}]}
    route = respx.get(f"{BASE_URL}/sets")
    route.side_effect = [Response(200, json=page1), Response(200, json=page2)]

    source = PokemonTcgCardSource(client=PokemonTcgClient(base_url=BASE_URL))
    sets = list(source.fetch_sets())
    assert [s.ptcg_set_id for s in sets] == ["a", "b", "c"]
    assert route.call_count == 2


@respx.mock
def test_non_200_raises_clear_error():
    respx.get(f"{BASE_URL}/sets").mock(return_value=Response(500, text="boom"))
    source = PokemonTcgCardSource(client=PokemonTcgClient(base_url=BASE_URL))
    try:
        list(source.fetch_sets())
    except RuntimeError as exc:
        assert "500" in str(exc)
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
