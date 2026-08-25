from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import SetDetailOut, SetOut
from app.services import sets as sets_service
from app.services.collection import get_or_create_default_collection

router = APIRouter(prefix="/sets", tags=["sets"])


@router.get("", response_model=list[SetOut])
def list_sets(db: Session = Depends(get_db)) -> list[SetOut]:
    return [SetOut.model_validate(s) for s in sets_service.list_sets(db)]


@router.get("/{ptcg_set_id}", response_model=SetDetailOut)
def get_set_detail(ptcg_set_id: str, db: Session = Depends(get_db)) -> SetDetailOut:
    collection = get_or_create_default_collection(db)
    detail = sets_service.get_set_detail(db, ptcg_set_id, collection.id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Set {ptcg_set_id!r} not found")
    return SetDetailOut.model_validate(detail)
