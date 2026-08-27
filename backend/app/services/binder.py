"""Binder CRUD and the binder read model. Plain dataclasses in/out (see docs/01-architecture.md
layer rules) -- reusable from the CLI without pulling in FastAPI.

Every mutation validates the affected spreads through `binder.layout.validate_placements` and
raises `LayoutError` *before* committing, so a rejected edit leaves the binder untouched. The
unique index on (binder_id, page_index, row, col) is only a backstop; this is the real guard.
"""
from dataclasses import asdict, dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.binder.layout import (
    AutoLayoutMode,
    LayoutCard,
    PlacementSpec,
    auto_layout,
    spread_of,
    spread_pages,
    validate_placements,
)
from app.models import Binder, BinderPlacement, Card, CardVariant, CollectionItem
from app.services.collection import get_or_create_default_collection

LAYOUT_JSON_VERSION = 1


class LayoutError(ValueError):
    """A mutation would break a layout invariant. Carries every violation, not just the first --
    a batch edit that breaks three rules should report three."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(slots=True)
class BinderData:
    name: str
    rows: int = 3
    cols: int = 3
    pages: int = 20
    is_side_loading: bool = True
    gutter_mm: int = 6
    notes: str | None = None


@dataclass(slots=True)
class PlacementView:
    """A placement joined to the card data the designer needs to draw it."""

    id: int
    page_index: int
    row: int
    col: int
    row_span: int
    col_span: int
    kind: str
    card_variant_id: int | None
    insert_asset_id: int | None
    spans_gutter: bool
    z_order: int
    card_name: str | None = None
    number: str | None = None
    rarity: str | None = None
    variant: str | None = None
    image_small: str | None = None
    image_large: str | None = None
    is_owned: bool = False


@dataclass(slots=True)
class BinderLayout:
    id: int
    name: str
    rows: int
    cols: int
    pages: int
    is_side_loading: bool
    gutter_mm: int
    notes: str | None
    placements: list[PlacementView] = field(default_factory=list)
    not_owned_count: int = 0


@dataclass(slots=True)
class PlacementBatch:
    """One user gesture. `clears` names cells to empty by coordinate, `upserts` the placements
    to write. A move is a clear plus an upsert; a swap is two upserts. Keeping a gesture in one
    batch is what makes undo a single inverse call."""

    upserts: list[PlacementSpec] = field(default_factory=list)
    clears: list[tuple[int, int, int]] = field(default_factory=list)


def create_binder(db: Session, data: BinderData) -> Binder:
    binder = Binder(
        name=data.name,
        rows=data.rows,
        cols=data.cols,
        pages=data.pages,
        is_side_loading=data.is_side_loading,
        gutter_mm=data.gutter_mm,
        notes=data.notes,
    )
    db.add(binder)
    db.commit()
    db.refresh(binder)
    return binder


def list_binders(db: Session) -> list[Binder]:
    return list(db.execute(select(Binder).order_by(Binder.created_at.desc())).scalars())


def get_binder(db: Session, binder_id: int) -> Binder | None:
    return db.get(Binder, binder_id)


def update_binder(db: Session, binder_id: int, data: BinderData) -> Binder | None:
    """Update a binder, refusing a resize that would strand existing placements.

    Shrinking the grid or the page count is the one edit here that can invalidate placements
    that were legal when made, so it runs the same validation a placement edit does.
    """
    binder = db.get(Binder, binder_id)
    if binder is None:
        return None
    binder.name = data.name
    binder.rows = data.rows
    binder.cols = data.cols
    binder.pages = data.pages
    binder.is_side_loading = data.is_side_loading
    binder.gutter_mm = data.gutter_mm
    binder.notes = data.notes

    errors = validate_placements(_specs_for_binder(db, binder_id), binder)
    if errors:
        db.rollback()
        raise LayoutError(errors)
    db.commit()
    db.refresh(binder)
    return binder


def delete_binder(db: Session, binder_id: int) -> bool:
    binder = db.get(Binder, binder_id)
    if binder is None:
        return False
    db.delete(binder)
    db.commit()
    return True


def _placement_rows(db: Session, binder_id: int) -> list[BinderPlacement]:
    return list(
        db.execute(
            select(BinderPlacement)
            .where(BinderPlacement.binder_id == binder_id)
            .order_by(
                BinderPlacement.page_index, BinderPlacement.row, BinderPlacement.col
            )
        ).scalars()
    )


def _to_spec(row: BinderPlacement) -> PlacementSpec:
    return PlacementSpec(
        page_index=row.page_index,
        row=row.row,
        col=row.col,
        kind=str(row.kind),
        row_span=row.row_span,
        col_span=row.col_span,
        card_variant_id=row.card_variant_id,
        insert_asset_id=row.insert_asset_id,
        spans_gutter=row.spans_gutter,
        z_order=row.z_order,
    )


def _specs_for_binder(db: Session, binder_id: int) -> list[PlacementSpec]:
    return [_to_spec(r) for r in _placement_rows(db, binder_id)]


def _owned_variant_ids(db: Session, variant_ids: list[int]) -> set[int]:
    """Which of these variants the default collection actually holds (quantity > 0).

    Reuses the default-collection lookup from services/collection.py rather than defining a
    second notion of "owned".
    """
    if not variant_ids:
        return set()
    collection = get_or_create_default_collection(db)
    rows = db.execute(
        select(CollectionItem.card_variant_id).where(
            CollectionItem.collection_id == collection.id,
            CollectionItem.card_variant_id.in_(variant_ids),
            CollectionItem.quantity > 0,
        )
    ).all()
    return {r[0] for r in rows}


def get_binder_layout(db: Session, binder_id: int) -> BinderLayout | None:
    """The designer read model: placements joined to card data, each flagged owned or not.

    The not-owned roll-up (3.11) is computed here rather than in the UI so the CLI reports the
    same number the badge shows. A binder plan that quietly assumes cards you do not have is a
    bad plan, so the count travels with the layout.
    """
    binder = db.get(Binder, binder_id)
    if binder is None:
        return None

    rows = _placement_rows(db, binder_id)
    variant_ids = [r.card_variant_id for r in rows if r.card_variant_id is not None]

    card_by_variant: dict[int, tuple[CardVariant, Card]] = {}
    if variant_ids:
        joined = db.execute(
            select(CardVariant, Card)
            .join(Card, CardVariant.card_id == Card.id)
            .where(CardVariant.id.in_(variant_ids))
        ).all()
        card_by_variant = {cv.id: (cv, card) for cv, card in joined}

    owned = _owned_variant_ids(db, variant_ids)

    placements: list[PlacementView] = []
    not_owned_count = 0
    for r in rows:
        view = PlacementView(
            id=r.id,
            page_index=r.page_index,
            row=r.row,
            col=r.col,
            row_span=r.row_span,
            col_span=r.col_span,
            kind=str(r.kind),
            card_variant_id=r.card_variant_id,
            insert_asset_id=r.insert_asset_id,
            spans_gutter=r.spans_gutter,
            z_order=r.z_order,
        )
        if r.card_variant_id is not None:
            pair = card_by_variant.get(r.card_variant_id)
            if pair is not None:
                variant, card = pair
                view.card_name = card.name
                view.number = card.number
                view.rarity = card.rarity
                view.variant = str(variant.variant)
                view.image_small = card.image_small
                view.image_large = card.image_large
            view.is_owned = r.card_variant_id in owned
            if not view.is_owned:
                not_owned_count += 1
        placements.append(view)

    return BinderLayout(
        id=binder.id,
        name=binder.name,
        rows=binder.rows,
        cols=binder.cols,
        pages=binder.pages,
        is_side_loading=binder.is_side_loading,
        gutter_mm=binder.gutter_mm,
        notes=binder.notes,
        placements=placements,
        not_owned_count=not_owned_count,
    )


def _affected_spreads(batch: PlacementBatch) -> set[int]:
    spreads = {spread_of(p.page_index) for p in batch.upserts}
    spreads |= {spread_of(page) for page, _, _ in batch.clears}
    return spreads


def apply_batch(db: Session, binder_id: int, batch: PlacementBatch) -> list[PlacementView]:
    """Apply one gesture atomically: clears, then upserts, validated as a whole first.

    Validation runs over the affected spreads *after* notionally applying the batch, so a swap
    (two upserts trading cells) is judged on its result rather than on the transient state
    where both cards momentarily occupy one pocket.
    """
    binder = db.get(Binder, binder_id)
    if binder is None:
        raise LookupError(f"Binder {binder_id} not found")

    existing = _placement_rows(db, binder_id)
    cleared = set(batch.clears)
    replaced = {(p.page_index, p.row, p.col) for p in batch.upserts}

    survivors = [
        _to_spec(r)
        for r in existing
        if (r.page_index, r.row, r.col) not in cleared
        and (r.page_index, r.row, r.col) not in replaced
    ]
    proposed = survivors + list(batch.upserts)

    spreads = _affected_spreads(batch)
    in_scope = [p for p in proposed if spread_of(p.page_index) in spreads]
    errors = validate_placements(in_scope, binder)
    if errors:
        raise LayoutError(errors)

    by_cell = {(r.page_index, r.row, r.col): r for r in existing}
    for cell in cleared | replaced:
        row = by_cell.get(cell)
        if row is not None:
            db.delete(row)
    db.flush()

    written: list[BinderPlacement] = []
    for p in batch.upserts:
        row = BinderPlacement(
            binder_id=binder_id,
            page_index=p.page_index,
            row=p.row,
            col=p.col,
            row_span=p.row_span,
            col_span=p.col_span,
            kind=p.kind,
            card_variant_id=p.card_variant_id,
            insert_asset_id=p.insert_asset_id,
            spans_gutter=p.spans_gutter,
            z_order=p.z_order,
        )
        db.add(row)
        written.append(row)
    db.commit()
    for row in written:
        db.refresh(row)

    return [
        PlacementView(
            id=r.id,
            page_index=r.page_index,
            row=r.row,
            col=r.col,
            row_span=r.row_span,
            col_span=r.col_span,
            kind=str(r.kind),
            card_variant_id=r.card_variant_id,
            insert_asset_id=r.insert_asset_id,
            spans_gutter=r.spans_gutter,
            z_order=r.z_order,
        )
        for r in written
    ]


def set_placement(db: Session, binder_id: int, placement: PlacementSpec) -> PlacementView:
    """Write one placement, replacing whatever occupied that cell."""
    return apply_batch(db, binder_id, PlacementBatch(upserts=[placement]))[0]


def move_placement(
    db: Session, binder_id: int, placement_id: int, page_index: int, row: int, col: int
) -> list[PlacementView]:
    """Move a placement to another cell. Dropping onto an occupied pocket swaps the two, which
    is what the spec asks the drag-and-drop surface to do."""
    source = db.get(BinderPlacement, placement_id)
    if source is None or source.binder_id != binder_id:
        raise LookupError(f"Placement {placement_id} not found in binder {binder_id}")

    origin = (source.page_index, source.row, source.col)
    if origin == (page_index, row, col):
        return []

    target = db.execute(
        select(BinderPlacement).where(
            BinderPlacement.binder_id == binder_id,
            BinderPlacement.page_index == page_index,
            BinderPlacement.row == row,
            BinderPlacement.col == col,
        )
    ).scalar_one_or_none()

    moved = _to_spec(source)
    moved.page_index, moved.row, moved.col = page_index, row, col
    batch = PlacementBatch(upserts=[moved], clears=[origin])
    if target is not None:
        swapped = _to_spec(target)
        swapped.page_index, swapped.row, swapped.col = origin
        batch.upserts.append(swapped)
        batch.clears = []
    return apply_batch(db, binder_id, batch)


def clear_placement(db: Session, binder_id: int, placement_id: int) -> bool:
    row = db.get(BinderPlacement, placement_id)
    if row is None or row.binder_id != binder_id:
        return False
    db.delete(row)
    db.commit()
    return True


def clear_binder(db: Session, binder_id: int) -> int:
    result = db.execute(delete(BinderPlacement).where(BinderPlacement.binder_id == binder_id))
    db.commit()
    return result.rowcount or 0


@dataclass(slots=True)
class AutoLayoutResult:
    placed: int
    unplaced: int
    pages_used: int
    # Cards in the set that own no `card_variant` row, so auto-layout could not place them at
    # all. Variants are derived from the price feed, so a card the feed has never priced has
    # nothing to place -- and it is disproportionately the chase cards (in Paldea Evolved it is
    # every Wo-Chien/Chi-Yu/Chien-Pao/Ting-Lu ex). Reported rather than silently dropped: a
    # binder plan that omits fourteen cards without saying so is a bad plan, the same reason
    # the optimizer surfaces its uncovered rarity spend.
    skipped_no_variant: int = 0


def apply_auto_layout(
    db: Session,
    binder_id: int,
    set_id: int,
    *,
    mode: AutoLayoutMode = AutoLayoutMode.SET_ORDER,
    canonical_only: bool = True,
    skip_reverse_holos: bool = False,
    group_by_rarity: bool = False,
    start_subset_on_new_page: bool = False,
    replace: bool = True,
) -> AutoLayoutResult:
    """Lay a set out into a binder. Replaces the existing layout unless `replace=False`.

    `canonical_only` mirrors the "owned" definition used elsewhere: one variant per card unless
    the caller wants the master-set treatment with every printing placed separately.
    """
    binder = db.get(Binder, binder_id)
    if binder is None:
        raise LookupError(f"Binder {binder_id} not found")

    stmt = (
        select(CardVariant, Card)
        .join(Card, CardVariant.card_id == Card.id)
        .where(Card.set_id == set_id)
    )
    if canonical_only:
        stmt = stmt.where(CardVariant.is_canonical.is_(True))
    rows = db.execute(stmt).all()

    cards = [
        LayoutCard(
            card_variant_id=variant.id,
            number=card.number,
            number_sort=card.number_sort,
            rarity=card.rarity,
            variant=str(variant.variant),
        )
        for variant, card in rows
    ]

    # Cards nothing in `card_variant` points at. Counted with its own query rather than as
    # (cards in set - cards reached above), because that subtraction would also sweep in cards
    # merely filtered out by `canonical_only` -- a deliberate choice by the caller, not a data
    # gap, and telling someone to ingest prices they already have would be wrong. The caller
    # otherwise has no way to tell "did not fit" from "was never placeable".
    skipped_no_variant = (
        db.execute(
            select(func.count(Card.id)).where(
                Card.set_id == set_id,
                ~select(CardVariant.id)
                .where(CardVariant.card_id == Card.id)
                .exists(),
            )
        ).scalar_one()
        or 0
    )
    placements = auto_layout(
        cards,
        binder,
        mode=mode,
        skip_reverse_holos=skip_reverse_holos,
        group_by_rarity=group_by_rarity,
        start_subset_on_new_page=start_subset_on_new_page,
    )

    errors = validate_placements(placements, binder)
    if errors:
        raise LayoutError(errors)

    if replace:
        db.execute(delete(BinderPlacement).where(BinderPlacement.binder_id == binder_id))
    for p in placements:
        db.add(
            BinderPlacement(
                binder_id=binder_id,
                page_index=p.page_index,
                row=p.row,
                col=p.col,
                row_span=p.row_span,
                col_span=p.col_span,
                kind=p.kind,
                card_variant_id=p.card_variant_id,
                insert_asset_id=p.insert_asset_id,
                spans_gutter=p.spans_gutter,
                z_order=p.z_order,
            )
        )
    db.commit()

    considered = len(cards)
    if skip_reverse_holos:
        considered = len([c for c in cards if c.variant != "reverse_holofoil"])
    pages_used = max((p.page_index for p in placements), default=-1) + 1
    return AutoLayoutResult(
        placed=len(placements),
        unplaced=considered - len(placements),
        pages_used=pages_used,
        skipped_no_variant=skipped_no_variant,
    )


def export_layout_json(db: Session, binder_id: int) -> dict | None:
    """Portable, diffable layout export.

    Card placements carry `ptcg_card_id` and `variant` alongside the local `card_variant_id`,
    because local ids are meaningless in another database. Import prefers the stable pair and
    falls back to the raw id.
    """
    binder = db.get(Binder, binder_id)
    if binder is None:
        return None

    rows = _placement_rows(db, binder_id)
    variant_ids = [r.card_variant_id for r in rows if r.card_variant_id is not None]
    identity: dict[int, tuple[str, str]] = {}
    if variant_ids:
        joined = db.execute(
            select(CardVariant, Card)
            .join(Card, CardVariant.card_id == Card.id)
            .where(CardVariant.id.in_(variant_ids))
        ).all()
        identity = {cv.id: (card.ptcg_card_id, str(cv.variant)) for cv, card in joined}

    placements = []
    for r in rows:
        entry: dict = {
            "page_index": r.page_index,
            "row": r.row,
            "col": r.col,
            "row_span": r.row_span,
            "col_span": r.col_span,
            "kind": str(r.kind),
            "card_variant_id": r.card_variant_id,
            "insert_asset_id": r.insert_asset_id,
            "spans_gutter": r.spans_gutter,
            "z_order": r.z_order,
        }
        if r.card_variant_id in identity:
            entry["ptcg_card_id"], entry["variant"] = identity[r.card_variant_id]
        placements.append(entry)

    return {
        "version": LAYOUT_JSON_VERSION,
        "binder": {
            "name": binder.name,
            "rows": binder.rows,
            "cols": binder.cols,
            "pages": binder.pages,
            "is_side_loading": binder.is_side_loading,
            "gutter_mm": binder.gutter_mm,
            "notes": binder.notes,
        },
        "placements": placements,
    }


def _resolve_variant(db: Session, entry: dict) -> int | None:
    """Map an exported placement back onto a local card_variant id."""
    ptcg_card_id = entry.get("ptcg_card_id")
    variant = entry.get("variant")
    if ptcg_card_id and variant:
        found = db.execute(
            select(CardVariant.id)
            .join(Card, CardVariant.card_id == Card.id)
            .where(Card.ptcg_card_id == ptcg_card_id, CardVariant.variant == variant)
        ).scalar_one_or_none()
        if found is not None:
            return found
    return entry.get("card_variant_id")


def import_layout_json(db: Session, payload: dict, binder_id: int | None = None) -> Binder:
    """Import a layout, into an existing binder if `binder_id` is given or a new one otherwise.

    Placements whose card is absent from this database are dropped rather than imported as
    dangling references, and the binder geometry from the payload wins -- a layout designed for
    a 3x4 binder is meaningless in a 3x3 one.
    """
    version = payload.get("version")
    if version != LAYOUT_JSON_VERSION:
        raise ValueError(
            f"Unsupported layout JSON version {version!r}; this build writes and reads "
            f"version {LAYOUT_JSON_VERSION}"
        )
    spec = payload.get("binder") or {}
    data = BinderData(
        name=spec.get("name", "Imported binder"),
        rows=spec.get("rows", 3),
        cols=spec.get("cols", 3),
        pages=spec.get("pages", 20),
        is_side_loading=spec.get("is_side_loading", True),
        gutter_mm=spec.get("gutter_mm", 6),
        notes=spec.get("notes"),
    )

    if binder_id is None:
        binder = create_binder(db, data)
    else:
        binder = db.get(Binder, binder_id)
        if binder is None:
            raise LookupError(f"Binder {binder_id} not found")
        db.execute(delete(BinderPlacement).where(BinderPlacement.binder_id == binder.id))
        binder.rows, binder.cols, binder.pages = data.rows, data.cols, data.pages
        binder.is_side_loading, binder.gutter_mm = data.is_side_loading, data.gutter_mm
        db.flush()

    specs: list[PlacementSpec] = []
    for entry in payload.get("placements", []):
        kind = entry.get("kind", "card")
        card_variant_id = _resolve_variant(db, entry) if kind == "card" else None
        if kind == "card" and card_variant_id is None:
            continue
        specs.append(
            PlacementSpec(
                page_index=entry["page_index"],
                row=entry["row"],
                col=entry["col"],
                kind=kind,
                row_span=entry.get("row_span", 1),
                col_span=entry.get("col_span", 1),
                card_variant_id=card_variant_id,
                insert_asset_id=entry.get("insert_asset_id") if kind == "insert" else None,
                spans_gutter=entry.get("spans_gutter", False),
                z_order=entry.get("z_order", 0),
            )
        )

    errors = validate_placements(specs, binder)
    if errors:
        db.rollback()
        raise LayoutError(errors)

    for p in specs:
        db.add(BinderPlacement(binder_id=binder.id, **asdict(p)))
    db.commit()
    db.refresh(binder)
    return binder


def spread_placements(layout: BinderLayout, spread_index: int) -> list[PlacementView]:
    """Placements on one spread, for previews and the print export."""
    left, right = spread_pages(spread_index)
    return [p for p in layout.placements if p.page_index in (left, right)]
