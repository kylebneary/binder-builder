"""DB-facing half of the Michi work: colour extraction and Michi auto-layout (roadmap 3.6 / 3.8).

`binder/color.py` and `binder/michi.py` are pure. This module reads cards, caches art, writes
`card.dominant_color_lab`, and turns scored spread plans into placements.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.binder.color import dominant_lab
from app.binder.michi import (
    ClusterKey,
    MichiCard,
    MichiResult,
    ScoreWeights,
    auto_layout_michi,
    plans_to_placements,
)
from app.binder.templates import default_templates
from app.models import Binder, Card, CardVariant, Set
from app.services.binder import write_placements
from app.services.binder_export import cached_card_art
from app.services.prices import get_current_prices


@dataclass(slots=True)
class ColorExtractionResult:
    considered: int
    extracted: int
    skipped_no_image: int
    skipped_unreadable: int
    already_cached: int


def extract_colors(
    db: Session,
    *,
    set_id: int | None = None,
    limit: int | None = None,
    refresh: bool = False,
    fetch: bool = True,
) -> ColorExtractionResult:
    """Cache each card's dominant colour as CIELAB (roadmap 3.6).

    Idempotent: cards that already have a value are skipped unless `refresh`. Art is pulled through
    the same on-disk cache the spread preview uses, so a second run over the same set does no
    network work at all.

    A card whose art will not download or will not decode is counted and skipped, never guessed --
    a fabricated colour would quietly corrupt every colour-themed layout built afterwards.
    """
    stmt = select(Card)
    if set_id is not None:
        stmt = stmt.where(Card.set_id == set_id)
    if not refresh:
        stmt = stmt.where(Card.dominant_color_lab.is_(None))
    stmt = stmt.order_by(Card.number_sort, Card.id)
    if limit is not None:
        stmt = stmt.limit(limit)

    cards = list(db.execute(stmt).scalars())
    extracted = no_image = unreadable = cached = 0
    for card in cards:
        if card.dominant_color_lab is not None and not refresh:
            cached += 1
            continue
        url = card.image_large or card.image_small
        path = cached_card_art(url, fetch=fetch)
        if path is None:
            no_image += 1
            continue
        lab = dominant_lab(path)
        if lab is None:
            unreadable += 1
            continue
        card.dominant_color_lab = [round(v, 4) for v in lab]
        extracted += 1
    db.commit()
    return ColorExtractionResult(
        considered=len(cards),
        extracted=extracted,
        skipped_no_image=no_image,
        skipped_unreadable=unreadable,
        already_cached=cached,
    )


def load_michi_cards(db: Session, set_id: int, *, canonical_only: bool = True) -> list[MichiCard]:
    """The pool for a Michi layout: one entry per placeable variant, with everything the
    clustering and scoring need attached."""
    stmt = (
        select(CardVariant, Card)
        .join(Card, CardVariant.card_id == Card.id)
        .where(Card.set_id == set_id)
    )
    if canonical_only:
        stmt = stmt.where(CardVariant.is_canonical.is_(True))
    rows = db.execute(stmt).all()

    product_ids = sorted({v.tcgplayer_product_id for v, _ in rows if v.tcgplayer_product_id})
    prices = get_current_prices(db, product_ids)

    cards: list[MichiCard] = []
    for variant, card in rows:
        market = None
        if variant.tcgplayer_product_id and variant.tcgplayer_sub_type_name:
            current = prices.get((variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name))
            if current and current["market"] is not None:
                market = float(current["market"])
        lab = card.dominant_color_lab
        dex = None
        if card.national_pokedex_numbers:
            # A card can list several (multi-Pokemon cards); the first is the one it is filed
            # under, which is what a species page should group on.
            dex = card.national_pokedex_numbers[0]
        cards.append(
            MichiCard(
                card_variant_id=variant.id,
                card_id=card.id,
                name=card.name,
                number_sort=card.number_sort,
                rarity=card.rarity,
                artist=card.artist,
                pokedex_number=dex,
                lab=tuple(lab) if lab else None,
                market_value=market,
            )
        )
    return cards


def apply_michi_layout(
    db: Session,
    binder_id: int,
    set_id: int,
    *,
    cluster_key: ClusterKey = ClusterKey.SPECIES,
    weights: ScoreWeights | None = None,
    trials: int = 24,
    seed: int = 0,
    canonical_only: bool = True,
) -> MichiResult:
    """Rewrite a binder as a Michi-curated layout.

    Replaces the whole binder, like the other auto-layout modes: the spread structure is chosen
    wholesale, so there is no meaningful way to merge it into an existing hand-made layout.
    """
    binder = db.get(Binder, binder_id)
    if binder is None:
        raise LookupError(f"Binder {binder_id} not found")
    if db.get(Set, set_id) is None:
        raise LookupError(f"Set {set_id} not found")

    cards = load_michi_cards(db, set_id, canonical_only=canonical_only)
    result = auto_layout_michi(
        cards,
        list(default_templates()),
        rows=binder.rows,
        cols=binder.cols,
        pages=binder.pages,
        is_side_loading=binder.is_side_loading,
        cluster_key=cluster_key,
        weights=weights,
        trials=trials,
        seed=seed,
    )

    # A template that validated but still produced an invalid layout means a bug in the template
    # or in the spread-coordinate conversion, not user error. write_placements validates before it
    # deletes, so the existing binder survives either way.
    write_placements(db, binder, plans_to_placements(result.plans))
    return result
