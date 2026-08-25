"""Orchestrates TcgCsvPriceSource into price_point upserts, plus card_variant derivation for
any tcgcsv group that's tied to a known Set.

Deriving card_variant rows here (rather than leaving it entirely to the future 1.6 set-mapping
work) requires knowing which tcgcsv groupId corresponds to which Set -- see the `--group`/`--set`
pairing in `bb ingest prices` (app/cli.py), which is a manual, one-off way to declare that link
until the general fuzzy set-name matcher (data/set_map.yaml, phase 1.5) exists.
"""
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.base import PricePointDTO, ProductDTO
from app.ingest.mapping import match_cards_in_set
from app.ingest.tcgcsv import TcgCsvPriceSource
from app.models import Card, CardVariant, PricePoint, Set
from app.models.enums import Variant

log = logging.getLogger(__name__)


def _to_decimal(value: float | None) -> Decimal | None:
    """PricePointDTO carries plain floats (the ingest boundary, per CLAUDE.md); the ORM column
    is Decimal. Convert through str, never straight from float, to avoid binary
    floating-point error creeping into a stored currency value."""
    if value is None:
        return None
    return Decimal(str(value))

# tcgcsv subTypeName -> Variant enum, per the verified list in docs/03-data-sources.md.
# NOTE: that list does not include the Prismatic-era Poke Ball Holo / Master Ball Holo
# subTypeName strings even though enums.Variant has members for them -- a documented gap.
# An unrecognized subTypeName is logged and skipped rather than guessed.
SUBTYPE_TO_VARIANT: dict[str, Variant] = {
    "Normal": Variant.NORMAL,
    "Holofoil": Variant.HOLOFOIL,
    "Reverse Holofoil": Variant.REVERSE_HOLOFOIL,
    "1st Edition Normal": Variant.FIRST_EDITION_NORMAL,
    "1st Edition Holofoil": Variant.FIRST_EDITION_HOLOFOIL,
    "Unlimited Holofoil": Variant.UNLIMITED_HOLOFOIL,
}

# Preference order for is_canonical when a card has more than one variant. Not specified by
# docs/02-data-model.md ("the variant counted by a non-master set goal") -- a documented
# assumption: prefer the plain print, then holo-only prints; reverse holo is never canonical
# since it's the master-set-only extra.
_CANONICAL_PREFERENCE = [
    Variant.NORMAL,
    Variant.HOLOFOIL,
    Variant.FIRST_EDITION_NORMAL,
    Variant.FIRST_EDITION_HOLOFOIL,
    Variant.UNLIMITED_HOLOFOIL,
    Variant.REVERSE_HOLOFOIL,
]


@dataclass(slots=True)
class GroupIngestResult:
    group_id: int
    n_price_points: int
    n_card_variants: int
    matched: bool
    error: str | None = None


def _upsert_price_point(db: Session, dto: PricePointDTO) -> None:
    row = db.execute(
        select(PricePoint).where(
            PricePoint.tcgplayer_product_id == dto.tcgplayer_product_id,
            PricePoint.sub_type_name == dto.sub_type_name,
            PricePoint.observed_on == dto.observed_on,
            PricePoint.source == dto.source,
        )
    ).scalar_one_or_none()
    if row is None:
        row = PricePoint(
            tcgplayer_product_id=dto.tcgplayer_product_id,
            sub_type_name=dto.sub_type_name,
            observed_on=dto.observed_on,
            source=dto.source,
        )
        db.add(row)
    row.low = _to_decimal(dto.low)
    row.mid = _to_decimal(dto.mid)
    row.high = _to_decimal(dto.high)
    row.market = _to_decimal(dto.market)
    row.direct_low = _to_decimal(dto.direct_low)
    row.currency = dto.currency


def _upsert_card_variant(db: Session, card_id: int, variant: Variant) -> CardVariant:
    row = db.execute(
        select(CardVariant).where(CardVariant.card_id == card_id, CardVariant.variant == variant)
    ).scalar_one_or_none()
    if row is None:
        row = CardVariant(card_id=card_id, variant=variant)
        db.add(row)
    return row


def _derive_variants(
    db: Session,
    set_row: Set,
    products: list[ProductDTO],
    prices_by_product: dict[int, list[PricePointDTO]],
) -> int:
    cards = list(db.execute(select(Card).where(Card.set_id == set_row.id)).scalars())
    cards_by_ptcg_id = {c.ptcg_card_id: c for c in cards}
    matches = match_cards_in_set(cards, products)

    n_touched = 0
    for m in matches:
        if m.tcgplayer_product_id is None or m.confidence < 1.0:
            if m.confidence < 1.0:
                log.warning(
                    "Skipping variant derivation for card %s: %s (confidence %.1f)",
                    m.ptcg_card_id,
                    m.reason,
                    m.confidence,
                )
            continue

        card = cards_by_ptcg_id[m.ptcg_card_id]
        present: list[tuple[Variant, str]] = []
        for price in prices_by_product.get(m.tcgplayer_product_id, []):
            variant = SUBTYPE_TO_VARIANT.get(price.sub_type_name)
            if variant is None:
                log.warning(
                    "Unrecognized subTypeName %r for product %s (card %s) -- skipping",
                    price.sub_type_name,
                    m.tcgplayer_product_id,
                    card.ptcg_card_id,
                )
                continue
            present.append((variant, price.sub_type_name))
        if not present:
            continue

        present_variants = {v for v, _ in present}
        canonical = next(
            (v for v in _CANONICAL_PREFERENCE if v in present_variants), present[0][0]
        )
        for variant, sub_type_name in present:
            row = _upsert_card_variant(db, card.id, variant)
            row.tcgplayer_product_id = m.tcgplayer_product_id
            row.tcgplayer_sub_type_name = sub_type_name
            row.is_canonical = variant == canonical
            n_touched += 1
    return n_touched


def resolve_group_set_pairs(
    db: Session,
    group_ids: list[int] | None,
    set_ids: list[str] | None,
    all_group_ids: Callable[[], list[int]],
) -> list[tuple[int, str | None]]:
    """Turn `--group`/`--set` CLI options into (group_id, ptcg_set_id | None) pairs.

    - Both given, equal counts: paired 1:1, in order -- an explicit "this group is this set"
      declaration (`ingest_group_prices` persists it on `Set.tcgplayer_group_id`).
    - `--group` only: filters to those groups; matching runs only if a `Set` already has that
      `tcgplayer_group_id` from a prior paired call.
    - `--set` only: looks up each set's already-mapped `tcgplayer_group_id`; raises if any set
      isn't mapped yet, rather than silently skipping it.
    - Neither: every tcgcsv group (`all_group_ids()`), matching wherever a `Set` is already linked.

    Raises ValueError (never silently guesses) for unequal --group/--set counts or an unmapped
    --set.
    """
    if group_ids and set_ids:
        if len(group_ids) != len(set_ids):
            raise ValueError(
                "--group and --set must be given the same number of times to pair them "
                f"(got {len(group_ids)} --group, {len(set_ids)} --set)"
            )
        return list(zip(group_ids, set_ids, strict=True))

    if group_ids:
        return [(g, None) for g in group_ids]

    if set_ids:
        pairs: list[tuple[int, str | None]] = []
        unmapped: list[str] = []
        for ref in set_ids:
            set_row = db.execute(select(Set).where(Set.ptcg_set_id == ref)).scalar_one_or_none()
            if set_row is None or set_row.tcgplayer_group_id is None:
                unmapped.append(ref)
                continue
            pairs.append((set_row.tcgplayer_group_id, ref))
        if unmapped:
            raise ValueError(
                "no tcgplayer_group_id mapped yet for: "
                + ", ".join(unmapped)
                + " -- use `--group N --set <id>` to link them first"
            )
        return pairs

    return [(g, None) for g in all_group_ids()]


def ingest_group_prices(
    db: Session,
    source: TcgCsvPriceSource,
    as_of: date,
    group_set_pairs: list[tuple[int, str | None]],
) -> list[GroupIngestResult]:
    """Ingest price_point rows for each (group_id, ptcg_set_id) pair.

    `ptcg_set_id` may be None: if a `Set` with that `tcgplayer_group_id` already exists (from a
    prior paired call), variant matching still runs against it; otherwise matching is skipped for
    that group and only price_point rows are written -- loudly logged, never silently skipped.
    Each group is its own transaction (partial-safe, per docs/01-architecture.md).
    """
    results: list[GroupIngestResult] = []
    for group_id, set_ref in group_set_pairs:
        try:
            if set_ref is not None:
                set_row = db.execute(
                    select(Set).where(Set.ptcg_set_id == set_ref)
                ).scalar_one_or_none()
                if set_row is None:
                    raise ValueError(
                        f"no Set row for ptcg_set_id={set_ref!r} -- "
                        f"run 'bb ingest cards --set {set_ref}' first"
                    )
                set_row.tcgplayer_group_id = group_id
                db.flush()
            else:
                set_row = db.execute(
                    select(Set).where(Set.tcgplayer_group_id == group_id)
                ).scalar_one_or_none()

            prices = list(source.client.fetch_group_prices(group_id, as_of))
            for price in prices:
                _upsert_price_point(db, price)

            n_variants = 0
            if set_row is not None:
                products = list(source.client.fetch_products(group_id))
                prices_by_product: dict[int, list[PricePointDTO]] = {}
                for price in prices:
                    prices_by_product.setdefault(price.tcgplayer_product_id, []).append(price)
                n_variants = _derive_variants(db, set_row, products, prices_by_product)
            else:
                log.warning(
                    "Group %s has no linked Set -- price_point rows written, card_variant "
                    "matching skipped. Pass --set to link it: `bb ingest prices --group %s "
                    "--set <ptcg_set_id>`.",
                    group_id,
                    group_id,
                )

            db.commit()
            results.append(
                GroupIngestResult(group_id, len(prices), n_variants, matched=set_row is not None)
            )
        except Exception as exc:
            db.rollback()
            log.error("Failed ingesting group %s: %s", group_id, exc)
            results.append(GroupIngestResult(group_id, 0, 0, matched=False, error=str(exc)))
    return results
