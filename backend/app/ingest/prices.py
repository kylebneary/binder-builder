"""Orchestrates TcgCsvPriceSource into price_point upserts, plus card_variant derivation for
any tcgcsv group that's tied to a known Set.

Deriving card_variant rows here (rather than leaving it entirely to the future 1.6 set-mapping
work) requires knowing which tcgcsv groupId corresponds to which Set -- see the `--group`/`--set`
pairing in `bb ingest prices` (app/cli.py), which is a manual, one-off way to declare that link
until the general fuzzy set-name matcher (data/set_map.yaml, phase 1.5) exists.
"""
import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.base import PricePointDTO, ProductDTO
from app.ingest.mapping import match_cards_in_set, match_tagged_products
from app.ingest.placeholders import retire_placeholders
from app.ingest.printing_tags import EditionGroup, default_registry
from app.ingest.sealed import upsert_sealed_products
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
    # WotC-era non-holo cards (Jungle through Neo Destiny) use the bare edition names.
    "1st Edition": Variant.FIRST_EDITION_NORMAL,
    "Unlimited": Variant.UNLIMITED_NORMAL,
}

# Preference order for is_canonical when a card has more than one variant. Not specified by
# docs/02-data-model.md ("the variant counted by a non-master set goal") -- a documented
# assumption: prefer the plain print, then holo-only prints, then unlimited over 1st Edition (the
# common, cheaper copy a plain set goal means); reverse holo is never canonical since it's the
# master-set-only extra.
_CANONICAL_PREFERENCE = [
    Variant.NORMAL,
    Variant.HOLOFOIL,
    Variant.UNLIMITED_NORMAL,
    Variant.UNLIMITED_HOLOFOIL,
    Variant.SHADOWLESS_NORMAL,
    Variant.SHADOWLESS_HOLOFOIL,
    Variant.FIRST_EDITION_NORMAL,
    Variant.FIRST_EDITION_HOLOFOIL,
    Variant.REVERSE_HOLOFOIL,
]


@dataclass(slots=True)
class GroupIngestResult:
    group_id: int
    n_price_points: int
    n_card_variants: int
    n_sealed_products: int
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


def _upsert_card_variant(db: Session, card_id: int, variant: str) -> CardVariant:
    row = db.execute(
        select(CardVariant).where(CardVariant.card_id == card_id, CardVariant.variant == variant)
    ).scalar_one_or_none()
    if row is None:
        row = CardVariant(card_id=card_id, variant=variant)
        db.add(row)
    return row


@dataclass(slots=True)
class _Printing:
    """One printing a card will get: what it is called, which (product, subType) prices it."""

    variant: str
    product_id: int
    sub_type_name: str
    is_special: bool


def _base_printings(
    product_id: int,
    prices: list[PricePointDTO],
    card_id: str,
    subtypes: Mapping[str, str] = SUBTYPE_TO_VARIANT,
) -> list[_Printing]:
    """A card's own product: one printing per recognised subTypeName. An edition group passes
    its own `subtypes`, since its "Unlimited" means a different print run."""
    out: list[_Printing] = []
    for price in prices:
        variant = subtypes.get(price.sub_type_name)
        if variant is None:
            log.warning(
                "Unrecognized subTypeName %r for product %s (card %s) -- skipping",
                price.sub_type_name,
                product_id,
                card_id,
            )
            continue
        out.append(_Printing(str(variant), product_id, price.sub_type_name, is_special=False))
    return out


def _derive_variants(
    db: Session,
    set_row: Set,
    products: list[ProductDTO],
    prices_by_product: dict[int, list[PricePointDTO]],
    edition_group: EditionGroup | None = None,
) -> int:
    """Derive card_variant rows for a set from its products, in two passes.

    1. `match_cards_in_set`: each card's own, untagged product.
    2. `match_tagged_products`: products whose names carry bracketed tags. A name-tag product
       ("Aerodactyl (Delta Species)") is the card's own product too; a printing-tag product
       ("Exeggcute (Poke Ball Pattern)", "Pikachu - 027 (Prerelease)") is an extra printing,
       keyed by its slug from data/printing_tags.yaml.

    Printings are gathered per card before anything is written, so the canonical printing is
    chosen from everything the card has, and a second product claiming a printing the card
    already has is reported rather than silently overwriting the first.

    With `edition_group` (a secondary print-run group such as Base Set (Shadowless)), subTypes
    are read through that group's own mapping and is_canonical is left alone: the set's primary
    group decides the canonical printing.
    """
    cards = list(db.execute(select(Card).where(Card.set_id == set_row.id)).scalars())
    cards_by_ptcg_id = {c.ptcg_card_id: c for c in cards}
    registry = default_registry()
    subtypes: Mapping[str, str] = edition_group.subtypes if edition_group else SUBTYPE_TO_VARIANT

    base: dict[str, list[_Printing]] = {}
    tagged: dict[str, list[_Printing]] = {}
    matched_products: set[int] = set()
    low_confidence: dict[str, str] = {}
    for m in match_cards_in_set(cards, products):
        if m.tcgplayer_product_id is None or m.confidence < 1.0:
            if m.confidence < 1.0:
                low_confidence[m.ptcg_card_id] = m.reason
            continue
        matched_products.add(m.tcgplayer_product_id)
        base.setdefault(m.ptcg_card_id, []).extend(
            _base_printings(
                m.tcgplayer_product_id,
                prices_by_product.get(m.tcgplayer_product_id, []),
                m.ptcg_card_id,
                subtypes,
            )
        )

    tagged_matches, unresolved = match_tagged_products(
        cards, products, matched_products, registry
    )
    for tm in tagged_matches:
        prices = prices_by_product.get(tm.tcgplayer_product_id, [])
        if tm.printing is None:
            base.setdefault(tm.ptcg_card_id, []).extend(
                _base_printings(tm.tcgplayer_product_id, prices, tm.ptcg_card_id, subtypes)
            )
            continue
        if len(prices) != 1:
            # A tagged printing is one product with one finish in every observed case; more
            # than one subType would need a second slug per finish, so report it instead.
            if prices:
                log.warning(
                    "Tagged printing %r (product %s) has %d subTypes -- skipping",
                    tm.printing.slug,
                    tm.tcgplayer_product_id,
                    len(prices),
                )
            continue
        tagged.setdefault(tm.ptcg_card_id, []).append(
            _Printing(
                tm.printing.slug,
                tm.tcgplayer_product_id,
                prices[0].sub_type_name,
                is_special=tm.printing.is_special,
            )
        )

    for ptcg_card_id, reason in low_confidence.items():
        if ptcg_card_id not in base:
            log.warning("Skipping variant derivation for card %s: %s", ptcg_card_id, reason)
    if unresolved:
        unknown = Counter(t for u in unresolved for t in u.unknown_tags)
        log.warning(
            "Set %s: %d tagged products left unmatched (%s). Unknown tags: %s -- add them to "
            "data/printing_tags.yaml if they are real printings.",
            set_row.ptcg_set_id,
            len(unresolved),
            ", ".join(f"{r}: {n}" for r, n in Counter(u.reason for u in unresolved).items()),
            ", ".join(f"{t!r} x{n}" for t, n in unknown.most_common(10)) or "none",
        )

    n_touched = 0
    priced_card_ids: list[int] = []
    for ptcg_card_id in base.keys() | tagged.keys():
        card = cards_by_ptcg_id[ptcg_card_id]
        printings = _resolve_printings(
            ptcg_card_id, base.get(ptcg_card_id, []), tagged.get(ptcg_card_id, [])
        )
        if not printings:
            continue
        canonical = _choose_canonical(printings)
        # An edition group defers to the primary group's canonical printing -- unless the
        # primary group never matched this card, which would leave it with none at all.
        decides_canonical = edition_group is None or not db.scalar(
            select(CardVariant.id).where(
                CardVariant.card_id == card.id,
                CardVariant.is_canonical.is_(True),
                CardVariant.variant != Variant.UNPRICED,
            )
        )
        for p in printings:
            row = _upsert_card_variant(db, card.id, p.variant)
            row.tcgplayer_product_id = p.product_id
            row.tcgplayer_sub_type_name = p.sub_type_name
            row.is_special = p.is_special
            if decides_canonical:
                row.is_canonical = p.variant == canonical
            n_touched += 1
        priced_card_ids.append(card.id)
    retire_placeholders(db, priced_card_ids)
    return n_touched


def _resolve_printings(
    ptcg_card_id: str, base: list[_Printing], tagged: list[_Printing]
) -> list[_Printing]:
    """One printing per variant name, base printings first.

    A special printing is only a variant when there is an unstamped card to vary from. Many
    promos were only ever released stamped, so when a card has no base printing and exactly one
    special product, that product IS the card: it is re-read as the card's base printing.
    """
    if not base and len(tagged) == 1 and tagged[0].is_special:
        only = tagged[0]
        variant = SUBTYPE_TO_VARIANT.get(only.sub_type_name)
        if variant is not None:
            tagged = []
            base = [_Printing(variant.value, only.product_id, only.sub_type_name, False)]

    out: dict[str, _Printing] = {}
    for p in [*base, *tagged]:
        if p.variant in out:
            if out[p.variant].product_id != p.product_id:
                log.warning(
                    "Card %s: printing %r claimed by products %s and %s -- keeping the first",
                    ptcg_card_id,
                    p.variant,
                    out[p.variant].product_id,
                    p.product_id,
                )
            continue
        out[p.variant] = p
    return list(out.values())


def _choose_canonical(printings: list[_Printing]) -> str:
    """Prefer the plain print, then holo-only prints (see _CANONICAL_PREFERENCE); a tagged
    printing is never canonical unless it is all the card has."""
    present = {p.variant for p in printings}
    for variant in _CANONICAL_PREFERENCE:
        if variant.value in present:
            return variant.value
    plain = [p for p in printings if not p.is_special]
    return (plain or printings)[0].variant


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
    - `--set` only: looks up each set's already-mapped `tcgplayer_group_id`, plus any edition
      groups for it (data/printing_tags.yaml); raises if any set isn't mapped yet, rather than
      silently skipping it.
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
            # Primary first, so its canonical choice is made before the extra print runs land.
            pairs.extend(
                (g.group_id, None)
                for g in default_registry().edition_groups.values()
                if g.ptcg_set_id == ref
            )
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
            # An edition group adds printings to a set whose primary group is elsewhere, so it
            # is never written to Set.tcgplayer_group_id (that would unlink the primary).
            edition_group = default_registry().edition_groups.get(group_id)
            if edition_group is not None:
                set_row = db.execute(
                    select(Set).where(Set.ptcg_set_id == edition_group.ptcg_set_id)
                ).scalar_one_or_none()
            elif set_ref is not None:
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

            # Fetched unconditionally: sealed products (set_id nullable, per docs/02-data-model.md)
            # are captured even for a group with no linked Set yet, not just card variants.
            products = list(source.client.fetch_products(group_id))
            n_sealed = upsert_sealed_products(db, products, set_row)

            n_variants = 0
            if set_row is not None:
                prices_by_product: dict[int, list[PricePointDTO]] = {}
                for price in prices:
                    prices_by_product.setdefault(price.tcgplayer_product_id, []).append(price)
                n_variants = _derive_variants(
                    db, set_row, products, prices_by_product, edition_group
                )
            else:
                log.warning(
                    "Group %s has no linked Set -- price_point/sealed_product rows written, "
                    "card_variant matching skipped. Pass --set to link it: `bb ingest prices "
                    "--group %s --set <ptcg_set_id>`.",
                    group_id,
                    group_id,
                )

            db.commit()
            results.append(
                GroupIngestResult(
                    group_id, len(prices), n_variants, n_sealed, matched=set_row is not None
                )
            )
        except Exception as exc:
            db.rollback()
            log.error("Failed ingesting group %s: %s", group_id, exc)
            results.append(GroupIngestResult(group_id, 0, 0, 0, matched=False, error=str(exc)))
    return results
