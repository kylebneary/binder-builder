"""Binder designer endpoints.

Placement edits go through one batch endpoint rather than per-pocket calls: a drag that swaps
two cards is a single gesture, and keeping it a single request is what lets the client undo it
with one inverse call.
"""
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import (
    AutoLayoutIn,
    AutoLayoutOut,
    BinderIn,
    BinderLayoutOut,
    BinderOut,
    InsertAssetOut,
    PlacementBatchIn,
    PlacementOut,
)
from app.binder.export import SHEETS_MM, ExportError
from app.binder.layout import AutoLayoutMode, PlacementSpec
from app.services import binder as binder_service
from app.services import binder_export
from app.services import inserts as inserts_service
from app.services.binder import BinderData, LayoutError, PlacementBatch
from app.services.inserts import InsertError

router = APIRouter(prefix="/binders", tags=["binders"])


def _data(body: BinderIn) -> BinderData:
    return BinderData(
        name=body.name,
        rows=body.rows,
        cols=body.cols,
        pages=body.pages,
        is_side_loading=body.is_side_loading,
        gutter_mm=body.gutter_mm,
        notes=body.notes,
    )


# --- insert assets (3.4) ------------------------------------------------------------------------
# Declared before /{binder_id}: FastAPI matches in declaration order, and "inserts" would
# otherwise be parsed as a binder id and 422 rather than reaching these.


@router.get("/inserts", response_model=list[InsertAssetOut])
def list_inserts(db: Session = Depends(get_db)) -> list[InsertAssetOut]:
    return [InsertAssetOut.model_validate(a) for a in inserts_service.list_inserts(db)]


@router.post("/inserts", response_model=InsertAssetOut, status_code=201)
async def upload_insert(
    file: Annotated[UploadFile, File(description="The artwork; raster only.")],
    name: Annotated[str, Form()] = "",
    width_pockets: Annotated[int, Form()] = 1,
    height_pockets: Annotated[int, Form()] = 1,
    source_note: Annotated[str | None, Form()] = None,
    db: Session = Depends(get_db),
) -> InsertAssetOut:
    """Store an insert, refusing anything that cannot print at 300 DPI at its target size.

    422 rather than 400 on a too-small image: it is a validation failure about the body's content,
    and the message carries the pixel dimensions the file would need.
    """
    data = await file.read()
    try:
        asset = inserts_service.save_insert(
            db,
            name=name,
            data=data,
            filename=file.filename or "upload",
            width_pockets=width_pockets,
            height_pockets=height_pockets,
            source_note=source_note,
        )
    except InsertError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return InsertAssetOut.model_validate(asset)


@router.delete("/inserts/{insert_id}", status_code=204)
def delete_insert(insert_id: int, db: Session = Depends(get_db)) -> None:
    try:
        deleted = inserts_service.delete_insert(db, insert_id)
    except InsertError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Insert {insert_id} not found")


@router.get("", response_model=list[BinderOut])
def list_binders(db: Session = Depends(get_db)) -> list[BinderOut]:
    return [BinderOut.model_validate(b) for b in binder_service.list_binders(db)]


@router.post("", response_model=BinderOut, status_code=201)
def create_binder(body: BinderIn, db: Session = Depends(get_db)) -> BinderOut:
    return BinderOut.model_validate(binder_service.create_binder(db, _data(body)))


@router.get("/{binder_id}", response_model=BinderOut)
def get_binder(binder_id: int, db: Session = Depends(get_db)) -> BinderOut:
    binder = binder_service.get_binder(db, binder_id)
    if binder is None:
        raise HTTPException(status_code=404, detail=f"Binder {binder_id} not found")
    return BinderOut.model_validate(binder)


@router.patch("/{binder_id}", response_model=BinderOut)
def update_binder(binder_id: int, body: BinderIn, db: Session = Depends(get_db)) -> BinderOut:
    try:
        binder = binder_service.update_binder(db, binder_id, _data(body))
    except LayoutError as exc:
        raise HTTPException(status_code=409, detail=exc.errors) from exc
    if binder is None:
        raise HTTPException(status_code=404, detail=f"Binder {binder_id} not found")
    return BinderOut.model_validate(binder)


@router.delete("/{binder_id}", status_code=204)
def delete_binder(binder_id: int, db: Session = Depends(get_db)) -> None:
    if not binder_service.delete_binder(db, binder_id):
        raise HTTPException(status_code=404, detail=f"Binder {binder_id} not found")


@router.get("/{binder_id}/layout", response_model=BinderLayoutOut)
def get_layout(binder_id: int, db: Session = Depends(get_db)) -> BinderLayoutOut:
    layout = binder_service.get_binder_layout(db, binder_id)
    if layout is None:
        raise HTTPException(status_code=404, detail=f"Binder {binder_id} not found")
    return BinderLayoutOut.model_validate(layout)


@router.put("/{binder_id}/placements", response_model=list[PlacementOut])
def put_placements(
    binder_id: int, body: PlacementBatchIn, db: Session = Depends(get_db)
) -> list[PlacementOut]:
    """Apply one gesture. Rejected batches leave the binder untouched and return 409 with every
    violation, so the client can surface the reason rather than a bare failure."""
    batch = PlacementBatch(
        upserts=[PlacementSpec(**p.model_dump()) for p in body.upserts],
        clears=[(c.page_index, c.row, c.col) for c in body.clears],
    )
    try:
        written = binder_service.apply_batch(db, binder_id, batch)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LayoutError as exc:
        raise HTTPException(status_code=409, detail=exc.errors) from exc
    return [PlacementOut.model_validate(p) for p in written]


@router.delete("/{binder_id}/placements/{placement_id}", status_code=204)
def delete_placement(binder_id: int, placement_id: int, db: Session = Depends(get_db)) -> None:
    if not binder_service.clear_placement(db, binder_id, placement_id):
        raise HTTPException(
            status_code=404, detail=f"Placement {placement_id} not found in binder {binder_id}"
        )


@router.post("/{binder_id}/auto-layout", response_model=AutoLayoutOut)
def post_auto_layout(
    binder_id: int, body: AutoLayoutIn, db: Session = Depends(get_db)
) -> AutoLayoutOut:
    try:
        mode = AutoLayoutMode(body.mode)
    except ValueError as exc:
        detail = f"Unknown auto-layout mode {body.mode!r}"
        raise HTTPException(status_code=422, detail=detail) from exc
    try:
        result = binder_service.apply_auto_layout(
            db,
            binder_id,
            body.set_id,
            mode=mode,
            canonical_only=body.canonical_only,
            skip_reverse_holos=body.skip_reverse_holos,
            group_by_rarity=body.group_by_rarity,
            start_subset_on_new_page=body.start_subset_on_new_page,
            replace=body.replace,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LayoutError as exc:
        raise HTTPException(status_code=409, detail=exc.errors) from exc
    return AutoLayoutOut.model_validate(result)


@router.get("/{binder_id}/layout.json")
def export_layout(binder_id: int, db: Session = Depends(get_db)) -> JSONResponse:
    payload = binder_service.export_layout_json(db, binder_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Binder {binder_id} not found")
    return JSONResponse(payload)


@router.post("/{binder_id}/layout.json", response_model=BinderOut)
def import_layout(binder_id: int, payload: dict, db: Session = Depends(get_db)) -> BinderOut:
    try:
        binder = binder_service.import_layout_json(db, payload, binder_id=binder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LayoutError as exc:
        raise HTTPException(status_code=409, detail=exc.errors) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BinderOut.model_validate(binder)


# --- print export (3.9 / 3.10) -------------------------------------------------------------------
# Both write to a temp file and stream it back. The alternative -- building in memory -- would mean
# a second code path for ReportLab and Pillow, when a file is what both libraries write natively
# and what the CLI needs anyway.


@router.get("/{binder_id}/export/inserts.pdf")
def export_inserts(
    binder_id: int,
    page_size: Annotated[str, Query(description=f"One of: {', '.join(SHEETS_MM)}")] = "letter",
    db: Session = Depends(get_db),
) -> FileResponse:
    """The print deliverable: every placed insert at exact trim size, bled, with crop marks."""
    tmp = Path(tempfile.mkdtemp(prefix="bb-inserts-")) / f"binder-{binder_id}-inserts.pdf"
    try:
        binder_export.export_binder_inserts_pdf(db, binder_id, tmp, page_size=page_size)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(tmp, media_type="application/pdf", filename=tmp.name)


@router.get("/{binder_id}/export/spread/{spread_index}.png")
def export_spread(
    binder_id: int,
    spread_index: int,
    dpi: Annotated[int, Query(ge=72, le=600)] = 150,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Preview one facing pair at true proportions."""
    name = f"binder-{binder_id}-spread-{spread_index}.png"
    tmp = Path(tempfile.mkdtemp(prefix="bb-spread-")) / name
    try:
        binder_export.export_binder_spread_png(db, binder_id, spread_index, tmp, dpi=dpi)
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FileResponse(tmp, media_type="image/png", filename=tmp.name)
