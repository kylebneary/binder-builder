"""Orchestrates a CardSource into set/card upserts. Idempotent on natural keys.

Kept out of `pokemontcg.py` so that module stays a pure adapter (fetch + DTO mapping) and this
stays swappable for any CardSource implementation.
"""
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.base import CardDTO, CardSource, SetDTO
from app.models import Card, Set

log = logging.getLogger(__name__)


@dataclass(slots=True)
class SetIngestResult:
    ptcg_set_id: str
    n_cards: int
    error: str | None = None


def derive_number_sort(number: str) -> int:
    """First run of digits in the card number, for ordering: 'TG12' -> 12, '025a' -> 25."""
    m = re.search(r"\d+", number)
    return int(m.group()) if m else 0


def _upsert_set(db: Session, dto: SetDTO) -> Set:
    row = db.execute(select(Set).where(Set.ptcg_set_id == dto.ptcg_set_id)).scalar_one_or_none()
    if row is None:
        row = Set(ptcg_set_id=dto.ptcg_set_id)
        db.add(row)
    row.name = dto.name
    row.series = dto.series
    row.printed_total = dto.printed_total
    row.total = dto.total
    row.release_date = dto.release_date
    row.ptcgo_code = dto.ptcgo_code
    row.symbol_url = dto.symbol_url
    row.logo_url = dto.logo_url
    db.flush()
    return row


def _upsert_card(db: Session, set_row: Set, dto: CardDTO) -> Card:
    row = db.execute(
        select(Card).where(Card.ptcg_card_id == dto.ptcg_card_id)
    ).scalar_one_or_none()
    if row is None:
        row = Card(ptcg_card_id=dto.ptcg_card_id)
        db.add(row)
    row.set_id = set_row.id
    row.number = dto.number
    row.number_sort = derive_number_sort(dto.number)
    row.name = dto.name
    row.supertype = dto.supertype
    row.rarity = dto.rarity
    row.artist = dto.artist
    row.subtypes = dto.subtypes
    row.types = dto.types
    row.national_pokedex_numbers = dto.national_pokedex_numbers
    row.image_small = dto.image_small
    row.image_large = dto.image_large
    return row


def ingest_sets_and_cards(
    db: Session, source: CardSource, set_refs: list[str] | None
) -> list[SetIngestResult]:
    """Upsert Set + Card rows for the given ptcg_set_ids, or every set if set_refs is None.

    Each set is its own transaction: one set's failure never blocks the others, and every
    failure is reported rather than swallowed -- see "Error handling" in docs/01-architecture.md.
    """
    all_sets = {dto.ptcg_set_id: dto for dto in source.fetch_sets()}

    def process(dto: SetDTO) -> SetIngestResult:
        try:
            cards = list(source.fetch_cards(dto.ptcg_set_id))
            set_row = _upsert_set(db, dto)
            for card_dto in cards:
                _upsert_card(db, set_row, card_dto)
            db.commit()
            return SetIngestResult(dto.ptcg_set_id, len(cards))
        except Exception as exc:
            db.rollback()
            log.error("Failed ingesting set %s: %s", dto.ptcg_set_id, exc)
            return SetIngestResult(dto.ptcg_set_id, 0, str(exc))

    if set_refs is None:
        return [process(dto) for dto in all_sets.values()]

    results: list[SetIngestResult] = []
    for ref in set_refs:
        dto = all_sets.get(ref)
        if dto is None:
            log.error("Unknown ptcg set id %r -- not present in pokemontcg.io /sets", ref)
            results.append(SetIngestResult(ref, 0, "unknown ptcg set id"))
            continue
        results.append(process(dto))
    return results
