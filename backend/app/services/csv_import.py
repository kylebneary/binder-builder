"""CSV import (roadmap 1.11): Collectr / TCG Collector / Deckbox exports.

None of these three tools publishes a stable CSV schema, and I don't have a verified real
export from any of them to test against (no live accounts, no sample files this session) -- so
rather than pretend precision with three rigid hardcoded per-tool profiles, this detects columns
by a flexible header-alias table covering the header names each tool plausibly uses (drawn from
general knowledge of these apps, NOT verified against a real export -- same "estimate, not fact"
posture the pull-rate YAML gets in docs/03-data-sources.md). The dry-run diff exists specifically
to let a real import be checked against that uncertainty before anything is written: it always
reports which CSV column was detected for which canonical field, and every row that couldn't be
matched -- never silently skipped, per the project's "never let a mismatch be silent" rule.
"""
import csv
import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.mapping import normalize_name, normalize_number
from app.models import Card, Set
from app.models.enums import Variant
from app.services.collection import (
    CollectionItemData,
    get_or_create_default_collection,
    upsert_collection_item,
)

log = logging.getLogger(__name__)

# canonical field -> header names (lowercased) that plausibly map to it across these tools.
HEADER_ALIASES: dict[str, list[str]] = {
    "set": ["set", "set name", "expansion", "edition"],
    "set_code": ["set code", "set abbreviation", "edition code", "ptcgo code"],
    "number": ["number", "card number", "collector number", "#", "no.", "card #", "card num"],
    "name": ["name", "card name", "card"],
    "printing": ["printing", "foil", "variant", "treatment", "finish", "rarity variant"],
    "condition": ["condition", "card condition"],
    "quantity": ["quantity", "qty", "count", "have", "have qty"],
    "price": ["price", "paid price", "purchase price", "cost", "price paid", "buy price"],
    "acquired_on": ["purchase date", "date acquired", "added", "date added"],
    "language": ["language", "lang"],
    "grade": ["grade"],
    "grader": ["grader", "grading company"],
}

# Set names as they commonly appear in third-party collection spreadsheets/exports, mapped to
# the canonical `set.name` this project ingests from pokemontcg.io. Discovered empirically against
# a real user export (see data/pokemon_cards.csv) -- not exhaustive, extend as new mismatches show
# up. Keys and values are compared case-insensitively.
SET_NAME_ALIASES: dict[str, str] = {
    "base set": "base",
    "sword and shield": "sword & shield",
    "sword and shield promos": "swsh black star promos",
    "pokemon go": "pokémon go",
    "guardian's rising": "guardians rising",
    "dragons exhaulted": "dragons exalted",
    "undaunted": "hs—undaunted",
    "brilliant stars (trainer gallery)": "brilliant stars trainer gallery",
    "lost origin (trainer gallery)": "lost origin trainer gallery",
    "silver tempest (trainer gallery)": "silver tempest trainer gallery",
    "crown zenith (galarian gallery)": "crown zenith galarian gallery",
    "celebrations classic collection": "celebrations: classic collection",
}

PRINTING_ALIASES: dict[str, Variant] = {
    "normal": Variant.NORMAL,
    "non holo": Variant.NORMAL,
    "non-holo": Variant.NORMAL,
    "holo": Variant.HOLOFOIL,
    "holofoil": Variant.HOLOFOIL,
    "reverse holo": Variant.REVERSE_HOLOFOIL,
    "reverse holofoil": Variant.REVERSE_HOLOFOIL,
    "reverse": Variant.REVERSE_HOLOFOIL,
    "1st edition holofoil": Variant.FIRST_EDITION_HOLOFOIL,
    "1st edition holo": Variant.FIRST_EDITION_HOLOFOIL,
    "1st edition normal": Variant.FIRST_EDITION_NORMAL,
    "1st edition": Variant.FIRST_EDITION_NORMAL,
    "unlimited holofoil": Variant.UNLIMITED_HOLOFOIL,
    "unlimited holo": Variant.UNLIMITED_HOLOFOIL,
}


@dataclass(slots=True)
class ParsedRow:
    line_number: int
    set_name: str | None
    set_code: str | None
    number: str | None
    name: str | None
    printing: str | None
    condition: str
    quantity: int
    price: Decimal | None
    acquired_on: date | None
    language: str
    grade: str | None
    grader: str | None


def _parse_int(raw: str | None, default: int = 1) -> int:
    if not raw or not raw.strip():
        return default
    try:
        return int(float(raw.strip()))
    except ValueError:
        return default


def _parse_price(raw: str | None) -> Decimal | None:
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip().replace("$", "").replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(raw: str | None) -> date | None:
    if not raw or not raw.strip():
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def detect_columns(fieldnames: Sequence[str]) -> dict[str, str]:
    """canonical field -> the actual CSV column name detected for it in this file."""
    normalized = {f.strip().lower(): f for f in fieldnames}
    mapping: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[canonical] = normalized[alias]
                break
    return mapping


def parse_csv(content: str) -> tuple[dict[str, str], list[ParsedRow]]:
    reader = csv.DictReader(io.StringIO(content))
    columns = detect_columns(reader.fieldnames or [])

    def get(row: dict, field: str) -> str | None:
        col = columns.get(field)
        return row.get(col) if col else None

    rows: list[ParsedRow] = []
    for line_number, raw_row in enumerate(reader, start=2):  # header is line 1
        rows.append(
            ParsedRow(
                line_number=line_number,
                set_name=get(raw_row, "set"),
                set_code=get(raw_row, "set_code"),
                number=get(raw_row, "number"),
                name=get(raw_row, "name"),
                printing=get(raw_row, "printing"),
                condition=(get(raw_row, "condition") or "NM").strip().upper() or "NM",
                quantity=_parse_int(get(raw_row, "quantity")),
                price=_parse_price(get(raw_row, "price")),
                acquired_on=_parse_date(get(raw_row, "acquired_on")),
                language=(get(raw_row, "language") or "EN").strip().upper() or "EN",
                grade=get(raw_row, "grade"),
                grader=get(raw_row, "grader"),
            )
        )
    return columns, rows


@dataclass(slots=True)
class ImportRowResult:
    line_number: int
    status: str  # "matched" | "no_set" | "ambiguous_set" | "no_card" | "no_variant"
    detail: str
    card_variant_id: int | None = None
    quantity: int = 0


def _resolve_set(db: Session, row: ParsedRow) -> Set | list[str] | None:
    """Returns the matched Set, or a list of candidate names if ambiguous, or None if no match."""
    if row.set_code:
        by_code = db.execute(select(Set).where(Set.ptcgo_code == row.set_code)).scalars().all()
        if len(by_code) == 1:
            return by_code[0]
    if not row.set_name:
        return None
    target = row.set_name.strip().lower()
    target = SET_NAME_ALIASES.get(target, target)
    all_sets = db.execute(select(Set)).scalars().all()
    exact = [s for s in all_sets if s.name.strip().lower() == target]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return [s.ptcg_set_id for s in exact]
    return None


def match_rows(db: Session, rows: list[ParsedRow]) -> list[ImportRowResult]:
    results: list[ImportRowResult] = []
    for row in rows:
        set_match = _resolve_set(db, row)
        if set_match is None:
            results.append(
                ImportRowResult(row.line_number, "no_set", f"no Set matches {row.set_name!r}")
            )
            continue
        if isinstance(set_match, list):
            detail = f"multiple sets match {row.set_name!r}: {set_match}"
            results.append(ImportRowResult(row.line_number, "ambiguous_set", detail))
            continue

        if not row.number:
            results.append(ImportRowResult(row.line_number, "no_card", "row has no card number"))
            continue
        target_number = normalize_number(row.number)
        candidates = [
            c
            for c in db.execute(select(Card).where(Card.set_id == set_match.id)).scalars()
            if normalize_number(c.number) == target_number
        ]
        card = None
        if len(candidates) == 1:
            card = candidates[0]
        elif len(candidates) > 1 and row.name:
            target_name = normalize_name(row.name)
            name_matches = [c for c in candidates if normalize_name(c.name) == target_name]
            if len(name_matches) == 1:
                card = name_matches[0]
        if card is None:
            results.append(
                ImportRowResult(
                    row.line_number,
                    "no_card",
                    f"no card #{row.number!r} in {set_match.ptcg_set_id!r}"
                    + (" (ambiguous)" if candidates else ""),
                )
            )
            continue

        variant = None
        detail_suffix = ""
        if row.printing:
            wanted = PRINTING_ALIASES.get(row.printing.strip().lower())
            if wanted is not None:
                variant = next((v for v in card.variants if v.variant == wanted), None)
            if variant is None:
                detail_suffix = (
                    f" (printing {row.printing!r} not recognized/available, used canonical)"
                )
        if variant is None:
            variant = next((v for v in card.variants if v.is_canonical), None)
        if variant is None:
            results.append(
                ImportRowResult(
                    row.line_number,
                    "no_variant",
                    f"card {card.ptcg_card_id} has no card_variant rows yet -- "
                    "run `bb ingest prices` for this set first",
                )
            )
            continue

        results.append(
            ImportRowResult(
                row.line_number,
                "matched",
                f"{card.ptcg_card_id} ({variant.variant}){detail_suffix}",
                card_variant_id=variant.id,
                quantity=row.quantity,
            )
        )
    return results


def dry_run_import(db: Session, rows: list[ParsedRow]) -> list[ImportRowResult]:
    return match_rows(db, rows)


def apply_import(db: Session, rows: list[ParsedRow]) -> list[ImportRowResult]:
    results = match_rows(db, rows)
    collection = get_or_create_default_collection(db)
    for result, row in zip(results, rows, strict=True):
        if result.status != "matched" or result.card_variant_id is None:
            continue
        upsert_collection_item(
            db,
            collection.id,
            CollectionItemData(
                card_variant_id=result.card_variant_id,
                quantity=row.quantity,
                condition=row.condition,
                language=row.language,
                grade=row.grade,
                grader=row.grader,
                acquired_price=row.price,
                acquired_on=row.acquired_on,
            ),
        )
    return results
