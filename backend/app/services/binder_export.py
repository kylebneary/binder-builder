"""Gathering the DB rows a binder export needs, and caching the art it draws (roadmap 3.9/3.10).

`binder/export.py` is pure geometry and never touches the network or the ORM. This is the layer
between: it reads the layout, resolves card art to local files, and hands plain dataclasses down.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.binder.export import (
    ExportError,
    InsertPiece,
    RenderPlacement,
    export_inserts_pdf,
    render_spread_png,
)
from app.config import get_settings
from app.models import InsertAsset
from app.services.binder import get_binder_layout, spread_placements

ART_TIMEOUT_S = 20.0


def card_art_dir() -> Path:
    return Path(get_settings().image_cache_dir) / "cards"


def cached_card_art(url: str | None, *, fetch: bool = True) -> str | None:
    """Local path for a card image, downloading it once if needed.

    Returns None rather than raising when the art cannot be fetched: a preview with a grey box
    where one card should be is far more useful than no preview at all, and the CDN being briefly
    unreachable is not the user's problem to solve. Cached by URL hash, so re-rendering a spread
    hits the disk.
    """
    if not url:
        return None
    suffix = Path(url.split("?")[0]).suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    path = card_art_dir() / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}{suffix}"
    if path.exists():
        return str(path)
    if not fetch:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        response = httpx.get(url, timeout=ART_TIMEOUT_S, follow_redirects=True)
        response.raise_for_status()
        path.write_bytes(response.content)
        return str(path)
    except (httpx.HTTPError, OSError):
        return None


def build_insert_pieces(db: Session, binder_id: int) -> list[InsertPiece]:
    """Every insert placed in the binder, as a printable piece.

    The *placement's* span decides the physical size, not the asset's declared span: an asset can
    be reused, and what matters for the sheet is how big the hole in the binder is.
    """
    layout = get_binder_layout(db, binder_id)
    if layout is None:
        raise ExportError(f"Binder {binder_id} not found.")

    insert_placements = [p for p in layout.placements if p.kind == "insert"]
    if not insert_placements:
        return []

    asset_ids = {p.insert_asset_id for p in insert_placements if p.insert_asset_id}
    assets = {
        a.id: a
        for a in db.execute(select(InsertAsset).where(InsertAsset.id.in_(asset_ids))).scalars()
    }

    pieces: list[InsertPiece] = []
    missing: list[int] = []
    for p in insert_placements:
        asset = assets.get(p.insert_asset_id or -1)
        if asset is None or not Path(asset.image_path).exists():
            missing.append(p.id)
            continue
        pieces.append(
            InsertPiece(
                name=asset.name,
                image_path=asset.image_path,
                width_pockets=p.col_span,
                height_pockets=p.row_span,
                page_index=p.page_index,
                row=p.row,
                col=p.col,
            )
        )
    if missing and not pieces:
        raise ExportError(
            f"Every insert placement in this binder ({len(missing)}) points at an asset whose "
            "image file is missing from the cache. Re-upload the artwork."
        )
    return pieces


def export_binder_inserts_pdf(
    db: Session, binder_id: int, out_path: str | Path, *, page_size: str = "letter"
) -> str:
    layout = get_binder_layout(db, binder_id)
    if layout is None:
        raise ExportError(f"Binder {binder_id} not found.")
    pieces = build_insert_pieces(db, binder_id)
    return export_inserts_pdf(pieces, out_path, page_size=page_size, binder_name=layout.name)


def export_binder_spread_png(
    db: Session,
    binder_id: int,
    spread_index: int,
    out_path: str | Path,
    *,
    dpi: int = 150,
    fetch_art: bool = True,
) -> str:
    """Render one spread. `fetch_art=False` keeps tests off the network."""
    layout = get_binder_layout(db, binder_id)
    if layout is None:
        raise ExportError(f"Binder {binder_id} not found.")
    if spread_index < 0 or spread_index * 2 >= layout.pages:
        last = (layout.pages - 1) // 2
        raise ExportError(
            f"Spread {spread_index} is outside binder {binder_id} -- it has {layout.pages} pages "
            f"(spreads 0-{last})."
        )

    assets: dict[int, InsertAsset] = {}
    placements = spread_placements(layout, spread_index)
    asset_ids = {p.insert_asset_id for p in placements if p.insert_asset_id}
    if asset_ids:
        assets = {
            a.id: a
            for a in db.execute(select(InsertAsset).where(InsertAsset.id.in_(asset_ids))).scalars()
        }

    renders: list[RenderPlacement] = []
    for p in placements:
        if p.kind == "insert":
            asset = assets.get(p.insert_asset_id or -1)
            image_path = asset.image_path if asset else None
            label = asset.name if asset else "insert"
        else:
            # Prefer the large art: it is downscaled into a pocket either way, and the small one
            # visibly softens at preview DPI.
            image_path = cached_card_art(p.image_large or p.image_small, fetch=fetch_art)
            label = p.card_name or "card"
        renders.append(
            RenderPlacement(
                row=p.row,
                col=p.col,
                row_span=p.row_span,
                col_span=p.col_span,
                # A gutter-spanning placement is stored on the even page and already carries
                # spread coordinates, so page_side must not shift it again -- see layout.py.
                page_side=0 if p.spans_gutter else p.page_index % 2,
                kind=p.kind,
                spans_gutter=p.spans_gutter,
                image_path=image_path,
                label=label,
                is_owned=p.is_owned or p.kind == "insert",
            )
        )

    return render_spread_png(
        renders,
        out_path,
        rows=layout.rows,
        cols=layout.cols,
        gutter_mm=layout.gutter_mm,
        dpi=dpi,
        binder_name=layout.name,
        spread_index=spread_index,
    )
