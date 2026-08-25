from app.ingest.base import ProductDTO
from app.ingest.mapping import (
    MatchResult,
    match_cards_in_set,
    normalize_name,
    normalize_number,
    strip_disambiguating_number,
)
from app.models import Card


def test_normalize_number_strips_set_size_and_zeros():
    assert normalize_number("021/128") == "21"
    assert normalize_number("TG12/TG30") == "TG12"
    assert normalize_number("025a") == "25A"
    assert normalize_number(None) is None


def test_normalize_name_drops_parenthetical_treatments():
    assert normalize_name("Charizard ex (Special Illustration Rare)") == "charizard ex"
    assert normalize_name("Pikachu (Full Art)") == "pikachu"
    assert normalize_name("Professor's Research") == "professors research"


def test_strip_disambiguating_number_undoes_tcgcsv_clean_name_suffix():
    # Real tcgcsv data: two "Alolan Dugtrio" cards (regular #123 and secret rare #208) get
    # cleanName "Alolan Dugtrio 123 191" / "Alolan Dugtrio 208 191" to stay distinct.
    # pokemontcg.io's name for both is just "Alolan Dugtrio".
    assert strip_disambiguating_number("Alolan Dugtrio 123 191", "123/191") == "Alolan Dugtrio"
    assert strip_disambiguating_number("Alolan Dugtrio 208 191", "208/191") == "Alolan Dugtrio"
    # A name with no disambiguating suffix, or a mismatched card_number, is left alone.
    assert strip_disambiguating_number("Alolan Diglett", "122/191") == "Alolan Diglett"
    assert strip_disambiguating_number("Alolan Dugtrio 123 191", None) == "Alolan Dugtrio 123 191"


def _product(product_id: int, number: str | None, name: str) -> ProductDTO:
    return ProductDTO(
        tcgplayer_product_id=product_id,
        tcgplayer_group_id=23651,
        name=name,
        clean_name=name,
        url=None,
        image_url=None,
        card_number=number,
        rarity="Common" if number else None,
    )


def _card(ptcg_card_id: str, number: str, name: str) -> Card:
    return Card(ptcg_card_id=ptcg_card_id, set_id=1, number=number, number_sort=0, name=name)


def test_match_cards_in_set_happy_path():
    cards = [_card("sv8-122", "122", "Alolan Diglett")]
    products = [_product(589855, "122/191", "Alolan Diglett")]
    results = match_cards_in_set(cards, products)
    assert results == [MatchResult("sv8-122", 589855, 1.0, "matched")]


def test_match_cards_in_set_no_number_match():
    cards = [_card("sv8-999", "999", "Made Up Card")]
    products = [_product(589855, "122/191", "Alolan Diglett")]
    results = match_cards_in_set(cards, products)
    assert len(results) == 1
    r = results[0]
    assert r.ptcg_card_id == "sv8-999"
    assert r.tcgplayer_product_id is None
    assert r.confidence == 0.0
    assert r.reason == "no number match"


def test_match_cards_in_set_number_matches_name_differs():
    cards = [_card("sv8-122", "122", "Wrong Name")]
    products = [_product(589855, "122/191", "Alolan Diglett")]
    results = match_cards_in_set(cards, products)
    r = results[0]
    assert r.tcgplayer_product_id == 589855
    assert r.confidence == 0.5
    assert "name differs" in r.reason


def test_match_cards_in_set_ambiguous_number_no_unique_name_winner():
    # Two products share a normalized number and neither name matches the card.
    cards = [_card("sv8-1", "1", "Bulbasaur")]
    products = [
        _product(1, "001/999", "Squirtle"),
        _product(2, "1/999", "Charmander"),
    ]
    results = match_cards_in_set(cards, products)
    r = results[0]
    assert r.tcgplayer_product_id is None
    assert r.confidence == 0.5
    assert r.reason == "ambiguous number match"


def test_match_cards_in_set_reports_every_card_never_silent():
    cards = [
        _card("sv8-122", "122", "Alolan Diglett"),
        _card("sv8-999", "999", "Unmatched Card"),
    ]
    products = [_product(589855, "122/191", "Alolan Diglett")]
    results = match_cards_in_set(cards, products)
    assert {r.ptcg_card_id for r in results} == {"sv8-122", "sv8-999"}
