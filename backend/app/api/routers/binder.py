"""Binder designer endpoints.

Placement edits go through one batch endpoint rather than per-pocket calls: a drag that swaps
two cards is a single gesture, and keeping it a single request is what lets the client undo it
with one inverse call.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import (
    AutoLayoutIn,
    AutoLayoutOut,
    BinderIn,
    BinderLayoutOut,
    BinderOut,
    PlacementBatchIn,
    PlacementOut,
)
from app.binder.layout import AutoLayoutMode, PlacementSpec
from app.services import binder as binder_service
from app.services.binder import BinderData, LayoutError, PlacementBatch

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
