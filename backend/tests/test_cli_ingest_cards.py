import json
from pathlib import Path

from app.ingest.base import CardDTO, SetDTO
from app.ingest.cards import SetIngestResult, ingest_sets_and_cards
from app.models import Card, Set
from sqlalchemy import func, select

FIXTURES = Path(__file__).parent / "fixtures"


class FakeCardSource:
    """CardSource backed by the recorded fixtures -- no network access."""

    name = "fake"

    def fetch_sets(self):
        data = json.loads((FIXTURES / "pokemontcg_sets.json").read_text())["data"]
        for raw in data:
            images = raw.get("images") or {}
            yield SetDTO(
                ptcg_set_id=raw["id"],
                name=raw["name"],
                series=raw.get("series"),
                printed_total=raw.get("printedTotal"),
                total=raw.get("total"),
                release_date=None,
                ptcgo_code=raw.get("ptcgoCode"),
                symbol_url=images.get("symbol"),
                logo_url=images.get("logo"),
            )

    def fetch_cards(self, set_ref: str):
        if set_ref != "sv8":
            return
        data = json.loads((FIXTURES / "pokemontcg_cards_sv8.json").read_text())["data"]
        for raw in data:
            images = raw.get("images") or {}
            yield CardDTO(
                ptcg_card_id=raw["id"],
                ptcg_set_id="sv8",
                number=raw["number"],
                name=raw["name"],
                supertype=raw.get("supertype"),
                rarity=raw.get("rarity"),
                artist=raw.get("artist"),
                subtypes=raw.get("subtypes") or [],
                types=raw.get("types") or [],
                national_pokedex_numbers=raw.get("nationalPokedexNumbers") or [],
                image_small=images.get("small"),
                image_large=images.get("large"),
            )


def test_ingest_sets_and_cards_is_idempotent(db):
    source = FakeCardSource()

    results1 = ingest_sets_and_cards(db, source, ["sv8"])
    assert results1 == [SetIngestResult("sv8", 3, None)]
    n_sets = db.execute(select(func.count()).select_from(Set)).scalar_one()
    n_cards = db.execute(select(func.count()).select_from(Card)).scalar_one()
    assert n_sets == 1
    assert n_cards == 3

    ingest_sets_and_cards(db, source, ["sv8"])
    assert db.execute(select(func.count()).select_from(Set)).scalar_one() == n_sets
    assert db.execute(select(func.count()).select_from(Card)).scalar_one() == n_cards

    diglett = db.execute(select(Card).where(Card.ptcg_card_id == "sv8-122")).scalar_one()
    assert diglett.number_sort == 122
    dugtrio_secret = db.execute(select(Card).where(Card.ptcg_card_id == "sv8-208")).scalar_one()
    assert dugtrio_secret.number_sort == 208


def test_ingest_unknown_set_reports_error_without_blocking_others(db):
    source = FakeCardSource()
    results = ingest_sets_and_cards(db, source, ["sv8", "does-not-exist"])
    by_id = {r.ptcg_set_id: r for r in results}
    assert by_id["sv8"].n_cards == 3
    assert by_id["sv8"].error is None
    assert by_id["does-not-exist"].error == "unknown ptcg set id"
    n_sets = db.execute(select(func.count()).select_from(Set)).scalar_one()
    assert n_sets == 1
