from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import (
    CollectionItemIn,
    CollectionItemOut,
    HoldingOut,
    PortfolioSummaryOut,
    PortfolioValuePointOut,
)
from app.services import collection as collection_service
from app.services import portfolio as portfolio_service

router = APIRouter(prefix="/collection", tags=["collection"])


@router.get("/items", response_model=list[CollectionItemOut])
def list_items(db: Session = Depends(get_db)) -> list[CollectionItemOut]:
    collection = collection_service.get_or_create_default_collection(db)
    items = collection_service.list_collection_items(db, collection.id)
    return [CollectionItemOut.model_validate(i) for i in items]


@router.put("/items", response_model=CollectionItemOut)
def upsert_item(body: CollectionItemIn, db: Session = Depends(get_db)) -> CollectionItemOut:
    """Upsert a holding on its natural key (card_variant_id, condition, language, is_graded,
    grade) -- PUT, not POST, since re-sending the same holding is idempotent by design."""
    collection = collection_service.get_or_create_default_collection(db)
    data = collection_service.CollectionItemData(
        card_variant_id=body.card_variant_id,
        quantity=body.quantity,
        condition=body.condition,
        language=body.language,
        is_graded=body.is_graded,
        grader=body.grader,
        grade=body.grade,
        acquired_price=body.acquired_price,
        acquired_on=body.acquired_on,
        storage_location=body.storage_location,
        notes=body.notes,
    )
    item = collection_service.upsert_collection_item(db, collection.id, data)
    return CollectionItemOut.model_validate(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)) -> None:
    collection = collection_service.get_or_create_default_collection(db)
    deleted = collection_service.delete_collection_item(db, collection.id, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Collection item {item_id} not found")


@router.get("/holdings", response_model=list[HoldingOut])
def list_holdings(db: Session = Depends(get_db)) -> list[HoldingOut]:
    """Every owned card with its set, price and storage location -- the holdings table.

    Returns the whole collection in one response so the client can sort and filter without a
    round trip per keystroke; see services/portfolio.list_holdings for why that is the right
    trade at this collection size.
    """
    collection = collection_service.get_or_create_default_collection(db)
    holdings = portfolio_service.list_holdings(db, collection.id)
    return [HoldingOut.model_validate(h) for h in holdings]


@router.get("/portfolio", response_model=PortfolioSummaryOut)
def portfolio_summary(db: Session = Depends(get_db)) -> PortfolioSummaryOut:
    collection = collection_service.get_or_create_default_collection(db)
    summary = portfolio_service.get_portfolio_summary(db, collection.id)
    return PortfolioSummaryOut.model_validate(summary)


@router.get("/portfolio/history", response_model=list[PortfolioValuePointOut])
def portfolio_value_history(db: Session = Depends(get_db)) -> list[PortfolioValuePointOut]:
    collection = collection_service.get_or_create_default_collection(db)
    points = portfolio_service.get_portfolio_value_history(db, collection.id)
    return [PortfolioValuePointOut.model_validate(p) for p in points]
