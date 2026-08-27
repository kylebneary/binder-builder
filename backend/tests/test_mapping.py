from app.ingest.base import ProductDTO
from app.ingest.mapping import (
    MatchResult,
    match_cards_in_set,
    normalize_name,
    normalize_number,
    strip_disambiguating_number,
    strip_known_treatment_suffix,
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


def test_strip_known_treatment_suffix_undoes_tcgcsv_clean_name_treatment_word():
    # Real tcgcsv data: "Dhelmise V (Full Art)" -> cleanName "Dhelmise V Full Art" (no punctuation
    # left to signal it's a parenthetical). pokemontcg.io's name for it is just "Dhelmise V".
    assert strip_known_treatment_suffix("Dhelmise V Full Art") == "Dhelmise V"
    assert strip_known_treatment_suffix("Charizard Rainbow Rare") == "Charizard"
    assert strip_known_treatment_suffix("Umbreon Gold") == "Umbreon"
    # A name with no known treatment suffix is left alone.
    assert strip_known_treatment_suffix("Alolan Diglett") == "Alolan Diglett"


def test_strip_known_treatment_suffix_prefers_longest_overlapping_match():
    # "full art" is itself a suffix of "alternate full art" -- stripping only the shorter one
    # would leave a dangling "Alternate" that still wouldn't match the card name.
    assert strip_known_treatment_suffix("Celebi V Alternate Full Art") == "Celebi V"
    assert strip_known_treatment_suffix("Inteleon VMAX Alternate Art Secret") == "Inteleon VMAX"


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


def test_match_cards_in_set_matches_through_known_treatment_suffix():
    # Real-world case (swsh1 "Dhelmise V", #187): tcgcsv's cleanName appends the special
    # treatment name; without recognizing that, this fell back to a 0.5 "name differs" match
    # instead of a confident 1.0 one, and the card ended up with zero priced card_variant rows
    # (docs/07-data-backlog.md item 3).
    cards = [_card("swsh1-187", "187", "Dhelmise V")]
    products = [_product(208385, "187/202", "Dhelmise V Full Art")]
    results = match_cards_in_set(cards, products)
    assert results == [MatchResult("swsh1-187", 208385, 1.0, "matched")]


def test_match_cards_in_set_reports_every_card_never_silent():
    cards = [
        _card("sv8-122", "122", "Alolan Diglett"),
        _card("sv8-999", "999", "Unmatched Card"),
    ]
    products = [_product(589855, "122/191", "Alolan Diglett")]
    results = match_cards_in_set(cards, products)
    assert {r.ptcg_card_id for r in results} == {"sv8-122", "sv8-999"}
