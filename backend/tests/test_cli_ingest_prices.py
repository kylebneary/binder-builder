import json
from datetime import date
from pathlib import Path

import pytest
import respx
from app.ingest.prices import (
    GroupIngestResult,
    ingest_group_prices,
    resolve_group_set_pairs,
)
from app.ingest.tcgcsv import TcgCsvClient, TcgCsvPriceSource
from app.models import Card, CardVariant, PricePoint, Set
from app.models.enums import Variant
from httpx import Response
from sqlalchemy import func, select

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://tcgcsv.test"
GROUP_ID = 23651
AS_OF = date(2026, 8, 25)


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


def _seed_sv8_cards(db) -> Set:
    """Mirrors the pokemontcg fixture cards used in test_cli_ingest_cards.py, minus the
    Alolan Exeggutor ex card (id sv8-133) so product 589858 stays deliberately unmatched."""
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", printed_total=191, total=252)
    db.add(set_row)
    db.flush()
    db.add_all(
        [
            Card(
                ptcg_card_id="sv8-122",
                set_id=set_row.id,
                number="122",
                number_sort=122,
                name="Alolan Diglett",
                rarity="Common",
            ),
            Card(
                ptcg_card_id="sv8-123",
                set_id=set_row.id,
                number="123",
                number_sort=123,
                name="Alolan Dugtrio",
                rarity="Uncommon",
            ),
            Card(
                ptcg_card_id="sv8-208",
                set_id=set_row.id,
                number="208",
                number_sort=208,
                name="Alolan Dugtrio",
                rarity="Illustration Rare",
            ),
        ]
    )
    db.commit()
    return set_row


def _source() -> TcgCsvPriceSource:
    return TcgCsvPriceSource(client=TcgCsvClient(base_url=BASE_URL, category_id=3))


@respx.mock
def test_ingest_group_prices_writes_price_points_and_variants_and_is_idempotent(db):
    _mock_group(respx.mock)
    _seed_sv8_cards(db)

    results1 = ingest_group_prices(db, _source(), AS_OF, [(GROUP_ID, "sv8")])
    # diglett (normal+reverse) + dugtrio 123 (normal+reverse) + dugtrio 208 (holofoil) = 5.
    # Product 589858 (Alolan Exeggutor ex #133) has no seeded card, so it contributes 0 --
    # matching is never silent about it (see the "skipping variant derivation" log), but it
    # doesn't block the other four cards from matching.
    assert results1 == [GroupIngestResult(GROUP_ID, 8, 5, matched=True)]

    n_prices = db.execute(select(func.count()).select_from(PricePoint)).scalar_one()
    n_variants = db.execute(select(func.count()).select_from(CardVariant)).scalar_one()
    assert n_prices == 8
    assert n_variants == 5

    # Set.tcgplayer_group_id was persisted by the explicit --group/--set pairing.
    set_row = db.execute(select(Set).where(Set.ptcg_set_id == "sv8")).scalar_one()
    assert set_row.tcgplayer_group_id == GROUP_ID

    # Re-run: no duplicate rows anywhere.
    ingest_group_prices(db, _source(), AS_OF, [(GROUP_ID, "sv8")])
    assert db.execute(select(func.count()).select_from(PricePoint)).scalar_one() == n_prices
    assert db.execute(select(func.count()).select_from(CardVariant)).scalar_one() == n_variants


@respx.mock
def test_variant_derivation_only_at_full_confidence(db):
    _mock_group(respx.mock)
    _seed_sv8_cards(db)
    ingest_group_prices(db, _source(), AS_OF, [(GROUP_ID, "sv8")])

    diglett = db.execute(select(Card).where(Card.ptcg_card_id == "sv8-122")).scalar_one()
    variants = db.execute(
        select(CardVariant).where(CardVariant.card_id == diglett.id)
    ).scalars().all()
    by_variant = {v.variant: v for v in variants}
    assert set(by_variant) == {Variant.NORMAL, Variant.REVERSE_HOLOFOIL}
    assert by_variant[Variant.NORMAL].is_canonical is True
    assert by_variant[Variant.REVERSE_HOLOFOIL].is_canonical is False
    assert by_variant[Variant.NORMAL].tcgplayer_product_id == 589855

    # sv8-208 (Alolan Dugtrio, Illustration Rare) matches product 589857 unambiguously too.
    dugtrio_secret = db.execute(select(Card).where(Card.ptcg_card_id == "sv8-208")).scalar_one()
    secret_variants = db.execute(
        select(CardVariant).where(CardVariant.card_id == dugtrio_secret.id)
    ).scalars().all()
    assert len(secret_variants) == 1
    assert secret_variants[0].variant == Variant.HOLOFOIL


@respx.mock
def test_group_without_linked_set_writes_prices_but_skips_variants(db):
    _mock_group(respx.mock)
    # No Set seeded at all -- --group used alone with nothing mapped yet.
    results = ingest_group_prices(db, _source(), AS_OF, [(GROUP_ID, None)])
    assert results == [GroupIngestResult(GROUP_ID, 8, 0, matched=False)]
    assert db.execute(select(func.count()).select_from(PricePoint)).scalar_one() == 8
    assert db.execute(select(func.count()).select_from(CardVariant)).scalar_one() == 0


def test_resolve_group_set_pairs_unequal_counts_raises(db):
    with pytest.raises(ValueError, match="same number of times"):
        resolve_group_set_pairs(db, [1, 2], ["sv8"], all_group_ids=lambda: [])


def test_resolve_group_set_pairs_unmapped_set_raises(db):
    db.add(Set(ptcg_set_id="sv8", name="Surging Sparks"))
    db.commit()
    with pytest.raises(ValueError, match="no tcgplayer_group_id mapped"):
        resolve_group_set_pairs(db, None, ["sv8"], all_group_ids=lambda: [])


def test_resolve_group_set_pairs_set_only_uses_existing_mapping(db):
    db.add(Set(ptcg_set_id="sv8", name="Surging Sparks", tcgplayer_group_id=GROUP_ID))
    db.commit()
    pairs = resolve_group_set_pairs(db, None, ["sv8"], all_group_ids=lambda: [])
    assert pairs == [(GROUP_ID, "sv8")]


def test_resolve_group_set_pairs_neither_given_uses_all_groups(db):
    pairs = resolve_group_set_pairs(db, None, None, all_group_ids=lambda: [1, 2, 3])
    assert pairs == [(1, None), (2, None), (3, None)]
