"""Binder layout engine. See docs/05-binder-spec.md.

Placements are axis-aligned rectangles on a pocket grid. A spread is a facing pair treated
as one rows x (2*cols) grid so art can cross the gutter -- which requires side-loading pages.

Coordinate convention -- the single most confusable thing in this module, read this before
touching anything below:

    Spread s covers pages (2s, 2s+1). Page 2s is the LEFT half, page 2s+1 the RIGHT half.

    * A normal placement stores per-page coordinates: `col` is 0..cols-1, relative to the
      page it sits on, and is bounds-checked against the rows x cols page grid.
    * A gutter-spanning placement (`spans_gutter=True`) is ALWAYS stored on the even (left)
      page of its spread, and its `col` is in SPREAD coordinates: 0..(2*cols)-1. It is
      bounds-checked against the rows x (2*cols) spread grid, must actually straddle the
      gutter, and requires a side-loading binder.

    `to_spread_rect` maps either form into spread coordinates, which is where overlap is
    checked -- a right-page placement at col 0 does not collide with a left-page one at
    col 0, but a gutter-spanning insert crossing into the right page collides with both.
"""
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

CARD_W_MM = 63
CARD_H_MM = 88
POCKET_W_MM = 70
POCKET_H_MM = 95
DEFAULT_GUTTER_MM = 6

# Ascending collectability order for rarity-tiered auto-layout. This is an ordering
# convention, not market data, so it lives in code rather than in an ingested table.
#
# Every string here was observed in the real catalogue -- the full set of 38 distinct
# `card.rarity` values across 20,479 ingested cards, not a guess at what the feed might emit.
# Regenerate the list after ingesting an era the project has not seen before:
#
#     SELECT rarity, COUNT(*) FROM card GROUP BY rarity ORDER BY 2 DESC;
#
# and check it against `test_every_known_rarity_string_is_ordered` in test_layout.py.
#
# The ordering within a tier is a judgement call about collectability, not a fact -- the
# Pokemon Company does not rank its own rarities. Two calls worth knowing about:
#   * `Promo` sits in the bulk tier. Promos are mass-distributed and mostly holo, so sorting
#     them by their holo-ness would strand a stack of energy promos in the chase pages.
#   * `Rare Holo Star` (gold stars) and `Rare Shining` rank near the top despite their plain
#     names; they are among the most sought-after old-era pulls.
#
# Rarities missing from this list still sort after everything in it, alphabetically, so a
# newly-ingested rarity lands in the chase pages rather than being mixed into the bulk. That
# is a safe default, not a good one: alphabetical is meaningless as an ordering, so add new
# strings here rather than relying on the fallback.
RARITY_ORDER: tuple[str, ...] = (
    # -- bulk ---------------------------------------------------------------------------
    "Common",
    "Uncommon",
    "Promo",
    # -- base rares ---------------------------------------------------------------------
    "Rare",
    "Black White Rare",
    "Rare Holo",
    "Classic Collection",
    # -- era-specific mid tiers ---------------------------------------------------------
    "Rare Prime",
    "Rare BREAK",
    "LEGEND",
    "Rare Prism Star",
    "Amazing Rare",
    "Radiant Rare",
    "ACE SPEC Rare",
    "Rare ACE",
    "Trainer Gallery Rare Holo",
    "Double Rare",
    # -- ultra rares --------------------------------------------------------------------
    "Rare Holo LV.X",
    "Rare Holo EX",
    "Rare Holo GX",
    "Rare Holo V",
    "Rare Holo VMAX",
    "Rare Holo VSTAR",
    "MEGA_ATTACK_RARE",
    "Ultra Rare",
    "Rare Ultra",
    # -- shinies ------------------------------------------------------------------------
    "Shiny Rare",
    "Rare Shiny",
    "Rare Shiny GX",
    "Shiny Ultra Rare",
    # -- chase --------------------------------------------------------------------------
    "Illustration Rare",
    "Special Illustration Rare",
    "Rare Rainbow",
    "Rare Secret",
    "Hyper Rare",
    "Mega Hyper Rare",
    "Rare Shining",
    "Rare Holo Star",
)


class AutoLayoutMode(StrEnum):
    SET_ORDER = "set_order"
    RARITY_TIERED = "rarity_tiered"


@dataclass(slots=True)
class Rect:
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1

    def overlaps(self, other: "Rect") -> bool:
        return not (
            self.row + self.row_span <= other.row
            or other.row + other.row_span <= self.row
            or self.col + self.col_span <= other.col
            or other.col + other.col_span <= self.col
        )


class BinderGeometry(Protocol):
    """The part of `models.Binder` that layout logic needs. Declared structurally so this
    module stays ORM-free and is testable against a plain object."""

    rows: int
    cols: int
    pages: int
    is_side_loading: bool


@dataclass(slots=True)
class Geometry:
    """Concrete BinderGeometry, for callers without an ORM row to hand."""

    rows: int = 3
    cols: int = 3
    pages: int = 20
    is_side_loading: bool = True


@dataclass(slots=True)
class PlacementSpec:
    """One placement, independent of the ORM: what the service layer validates and persists."""

    page_index: int
    row: int
    col: int
    kind: str = "card"
    row_span: int = 1
    col_span: int = 1
    card_variant_id: int | None = None
    insert_asset_id: int | None = None
    spans_gutter: bool = False
    z_order: int = 0

    @property
    def rect(self) -> Rect:
        return Rect(self.row, self.col, self.row_span, self.col_span)


def spread_of(page_index: int) -> int:
    """Which spread a page belongs to. Pages 0 and 1 are both spread 0."""
    return page_index // 2


def spread_pages(spread_index: int) -> tuple[int, int]:
    return (spread_index * 2, spread_index * 2 + 1)


def to_spread_rect(placement: PlacementSpec, cols: int) -> Rect:
    """Map a placement into its spread's rows x (2*cols) coordinate space.

    Gutter-spanning placements already store spread columns; per-page ones shift right by
    `cols` when they sit on an odd (right-hand) page.
    """
    if placement.spans_gutter:
        return placement.rect
    offset = 0 if placement.page_index % 2 == 0 else cols
    return Rect(placement.row, placement.col + offset, placement.row_span, placement.col_span)


def validate_page(rects: list[Rect], rows: int, cols: int) -> list[str]:
    """Return human-readable violations. Empty list means valid."""
    errors: list[str] = []
    for r in rects:
        if r.row < 0 or r.col < 0 or r.row + r.row_span > rows or r.col + r.col_span > cols:
            errors.append(f"placement at ({r.row},{r.col}) does not fit in {rows}x{cols} grid")
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            if a.overlaps(b):
                errors.append(f"placements at ({a.row},{a.col}) and ({b.row},{b.col}) overlap")
    return errors


def _bounds_errors(rect: Rect, rows: int, cols: int, where: str) -> list[str]:
    if (
        rect.row < 0
        or rect.col < 0
        or rect.row + rect.row_span > rows
        or rect.col + rect.col_span > cols
    ):
        return [f"{where} does not fit in the {rows}x{cols} grid"]
    return []


def validate_placements(placements: Sequence[PlacementSpec], binder: BinderGeometry) -> list[str]:
    """Full invariant check for a set of placements. Empty list means valid.

    Layers the reference and gutter invariants from docs/05-binder-spec.md on top of the
    bounds and overlap checks, and resolves overlap per spread rather than per page so that
    gutter-spanning art collides with whatever sits under it on the facing page.
    """
    errors: list[str] = []
    rows, cols = binder.rows, binder.cols

    for p in placements:
        where = f"placement at page {p.page_index} ({p.row},{p.col})"
        if p.page_index < 0 or p.page_index >= binder.pages:
            errors.append(f"{where} is outside the {binder.pages} pages of this binder")
        if p.row_span < 1 or p.col_span < 1:
            errors.append(f"{where} has a span below 1")
        if p.kind not in ("card", "insert", "empty"):
            errors.append(f"{where} has unknown kind {p.kind!r}")
        if p.kind == "card" and p.card_variant_id is None:
            errors.append(f"{where} has kind=card but no card_variant_id")
        if p.kind == "insert" and p.insert_asset_id is None:
            errors.append(f"{where} has kind=insert but no insert_asset_id")
        if p.kind == "empty" and (p.card_variant_id is not None or p.insert_asset_id is not None):
            errors.append(f"{where} has kind=empty but still references a card or insert")

        if p.spans_gutter:
            if not binder.is_side_loading:
                errors.append(
                    f"{where} spans the gutter, which requires a side-loading binder -- "
                    "a top-loading pocket lip would cut across the artwork"
                )
            if p.page_index % 2 != 0:
                errors.append(
                    f"{where} spans the gutter but sits on an odd page; gutter-spanning "
                    "placements are stored on the even (left) page of the spread"
                )
            if not p.col < cols < p.col + p.col_span:
                errors.append(
                    f"{where} is flagged spans_gutter but does not cross the gutter at "
                    f"column {cols}"
                )
            errors.extend(_bounds_errors(p.rect, rows, cols * 2, where))
        else:
            errors.extend(_bounds_errors(p.rect, rows, cols, where))

    # Overlap is a spread-level question, so group by spread and compare in spread coords.
    by_spread: dict[int, list[PlacementSpec]] = {}
    for p in placements:
        by_spread.setdefault(spread_of(p.page_index), []).append(p)
    for spread_index, group in sorted(by_spread.items()):
        rects = [(p, to_spread_rect(p, cols)) for p in group]
        for i, (pa, ra) in enumerate(rects):
            for pb, rb in rects[i + 1 :]:
                if ra.overlaps(rb):
                    errors.append(
                        f"placements at page {pa.page_index} ({pa.row},{pa.col}) and page "
                        f"{pb.page_index} ({pb.row},{pb.col}) overlap on spread {spread_index}"
                    )
    return errors


@dataclass(slots=True)
class LayoutCard:
    """One card offered to auto-layout. Plain data; the service maps ORM rows onto this."""

    card_variant_id: int
    number: str = ""
    number_sort: int = 0
    rarity: str | None = None
    variant: str = "normal"

    @property
    def subset(self) -> str:
        """Leading non-digit prefix of the card number: TG12 -> TG, 045 -> empty string.

        Subsets (Trainer Gallery, Galarian Gallery, the SV-numbered cards folded into a set)
        are numbered in their own sequence, which is what `start_subset_on_new_page` breaks on.
        """
        prefix = ""
        for ch in self.number:
            if ch.isdigit():
                break
            prefix += ch
        return prefix.upper()


def _rarity_rank(rarity: str | None) -> tuple[int, str]:
    if rarity is None:
        return (len(RARITY_ORDER) + 1, "")
    try:
        return (RARITY_ORDER.index(rarity), "")
    except ValueError:
        return (len(RARITY_ORDER), rarity)


def _break_key(
    mode: AutoLayoutMode, group_by_rarity: bool, start_subset_on_new_page: bool
) -> Callable[[LayoutCard], Any] | None:
    """What forces a page break, or None to fill pages continuously.

    Rarity is the coarser grouping and subset the finer one, so when both are asked for the
    key is the pair -- a new rarity starts a page, and so does a new subset within a rarity.
    """
    if mode == AutoLayoutMode.RARITY_TIERED:
        return lambda c: _rarity_rank(c.rarity)
    if group_by_rarity and start_subset_on_new_page:
        return lambda c: (_rarity_rank(c.rarity), c.subset)
    if group_by_rarity:
        return lambda c: _rarity_rank(c.rarity)
    if start_subset_on_new_page:
        return lambda c: c.subset
    return None


def auto_layout(
    cards: Iterable[LayoutCard],
    binder: BinderGeometry,
    *,
    mode: AutoLayoutMode = AutoLayoutMode.SET_ORDER,
    skip_reverse_holos: bool = False,
    group_by_rarity: bool = False,
    start_subset_on_new_page: bool = False,
) -> list[PlacementSpec]:
    """Fill pockets left-to-right, top-to-bottom. Set order is what most people want.

    One generator serves both non-Michi modes; they differ only in sort key and in what
    forces a page break:

    * SET_ORDER     -- `number_sort` order, optionally grouped by rarity within the set.
    * RARITY_TIERED -- ascending rarity, a fresh page per tier, so chase cards land last.

    Deterministic for a given input: ties in the sort key fall back to the card number, so
    the same pool always produces the same placements. Cards that do not fit in
    `binder.pages` are dropped, and the caller reports the shortfall.
    """
    pool = list(cards)
    if skip_reverse_holos:
        pool = [c for c in pool if c.variant != "reverse_holofoil"]

    if mode == AutoLayoutMode.RARITY_TIERED or group_by_rarity:
        pool.sort(key=lambda c: (_rarity_rank(c.rarity), c.number_sort, c.number))
    elif start_subset_on_new_page:
        pool.sort(key=lambda c: (c.subset, c.number_sort, c.number))
    else:
        pool.sort(key=lambda c: (c.number_sort, c.number))

    break_key = _break_key(mode, group_by_rarity, start_subset_on_new_page)
    per_page = binder.rows * binder.cols
    placements: list[PlacementSpec] = []
    page = 0
    slot = 0
    previous: Any = _UNSET
    for card in pool:
        if break_key is not None:
            current = break_key(card)
            if previous is not _UNSET and current != previous and slot != 0:
                page += 1
                slot = 0
            previous = current
        if page >= binder.pages:
            break
        placements.append(
            PlacementSpec(
                page_index=page,
                row=slot // binder.cols,
                col=slot % binder.cols,
                kind="card",
                card_variant_id=card.card_variant_id,
            )
        )
        slot += 1
        if slot >= per_page:
            page += 1
            slot = 0
    return placements


_UNSET = object()


def auto_layout_michi(**kwargs):
    """Cluster -> allocate spreads -> pick template -> assign -> score. See spec for weights.

    Colour work is CIELAB / deltaE2000, never RGB. RGB distance does not match perception
    and produces visibly wrong colour-themed pages.
    """
    raise NotImplementedError  # TODO(phase-3.8)


def score_layout(**kwargs) -> float:
    """0.30*symmetry + 0.25*colour_coherence + 0.20*hero_centrality
       + 0.15*fill_balance - 0.10*orphan_penalty"""
    raise NotImplementedError  # TODO(phase-3.8)
