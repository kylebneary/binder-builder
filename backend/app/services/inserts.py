"""Insert assets: the printable artwork that shares pockets with real cards (roadmap 3.4).

The whole point of this module is the DPI gate. docs/05-binder-spec.md is emphatic that the
failure mode to avoid is silently printing something blurry -- you find out after the cardstock
is spent -- so an upload that cannot hit 300 DPI at its target physical size is refused with the
pixel dimensions it would need, not accepted with a warning nobody reads.

Files land under `settings.image_cache_dir / "inserts"`, which is configured but was unused
before this. Only the path is stored in the DB; the image itself is never in a row.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.binder.export import MIN_DPI, effective_dpi, required_pixels
from app.config import get_settings
from app.models import BinderPlacement, InsertAsset

# Formats Pillow reads reliably and ReportLab can embed. Deliberately not SVG: the export draws
# raster art at a measured DPI, and a vector source has no pixel dimensions to check.
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


class InsertError(ValueError):
    """An insert cannot be accepted, with a reason the uploader can act on."""


def inserts_dir() -> Path:
    return Path(get_settings().image_cache_dir) / "inserts"


def save_insert(
    db: Session,
    *,
    name: str,
    data: bytes,
    filename: str,
    width_pockets: int = 1,
    height_pockets: int = 1,
    source_note: str | None = None,
) -> InsertAsset:
    """Validate, store, and record one insert image.

    Raises InsertError for anything the uploader can fix: an unreadable file, an unsupported
    format, a silly pocket span, or art too small to print sharply.
    """
    if width_pockets < 1 or height_pockets < 1:
        raise InsertError("An insert must span at least one pocket in each direction.")

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise InsertError(f"Unsupported image type {suffix or '(none)'} -- use one of: {allowed}")

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # cheap structural check; invalidates the handle, so reopen to measure
        with Image.open(io.BytesIO(data)) as img:
            px_w, px_h = img.size
    except (UnidentifiedImageError, OSError) as exc:
        raise InsertError(f"Could not read {filename!r} as an image: {exc}") from exc

    dpi = effective_dpi(px_w, px_h, width_pockets, height_pockets)
    if dpi < MIN_DPI:
        need_w, need_h = required_pixels(width_pockets, height_pockets)
        raise InsertError(
            f"{filename} is {px_w}x{px_h} px, which is {dpi:.0f} DPI at "
            f"{width_pockets}x{height_pockets} pockets. Printing needs at least {MIN_DPI} DPI: "
            f"supply at least {need_w}x{need_h} px, or place it across more pockets."
        )

    # Content-addressed: re-uploading the same art reuses the file instead of littering the cache.
    digest = hashlib.sha256(data).hexdigest()[:16]
    target_dir = inserts_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(data)

    asset = InsertAsset(
        name=name.strip() or Path(filename).stem,
        image_path=str(path),
        width_pockets=width_pockets,
        height_pockets=height_pockets,
        dpi=int(dpi),
        source_note=source_note,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def list_inserts(db: Session) -> list[InsertAsset]:
    return list(db.execute(select(InsertAsset).order_by(InsertAsset.id.desc())).scalars())


def get_insert(db: Session, insert_id: int) -> InsertAsset | None:
    return db.get(InsertAsset, insert_id)


def delete_insert(db: Session, insert_id: int) -> bool:
    """Remove an insert. Refuses while it is still placed in a binder -- deleting it would leave
    placements pointing at nothing, and `kind=insert` requires an `insert_asset_id`.

    The image file is left on disk: it is content-addressed and may be shared with another asset
    row, and orphaned art is cheap next to deleting something a second binder still uses.
    """
    asset = db.get(InsertAsset, insert_id)
    if asset is None:
        return False
    placed = db.execute(
        select(BinderPlacement.binder_id).where(BinderPlacement.insert_asset_id == insert_id)
    ).all()
    if placed:
        binders = sorted({row[0] for row in placed})
        raise InsertError(
            f"Insert {insert_id} is still placed in binder(s) {binders}. "
            "Remove those placements first."
        )
    db.delete(asset)
    db.commit()
    return True
