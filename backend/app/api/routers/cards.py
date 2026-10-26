"""Catalogue-wide card search -- the builder behind custom goals and goal-driven binders.

Search is a POST with a JSON body rather than a GET with query parameters: the filter has a dozen
list-valued fields, and the same body shape is what a filter goal stores and what "add every
match to this goal" sends, so one schema serves all three.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import CardFacetsOut, CardQueryIn, CardSearchIn, CardSearchOut
from app.services import cards as cards_service
from app.services.cards import CardQuery
from app.services.collection import get_or_create_default_collection

router = APIRouter(prefix="/cards", tags=["cards"])


def to_card_query(body: CardQueryIn) -> CardQuery:
    return CardQuery(**body.model_dump(include=set(CardQueryIn.model_fields)))


@router.post("/search", response_model=CardSearchOut)
def search_cards(body: CardSearchIn, db: Session = Depends(get_db)) -> CardSearchOut:
    collection = get_or_create_default_collection(db)
    result = cards_service.search_cards(
        db,
        to_card_query(body),
        collection_id=collection.id,
        sort=body.sort,
        offset=body.offset,
        limit=body.limit,
    )
    return CardSearchOut.model_validate(result)


@router.get("/facets", response_model=CardFacetsOut)
def card_facets(db: Session = Depends(get_db)) -> CardFacetsOut:
    """Every distinct value each filter can take, with card counts. Changes only on ingest, so
    the client caches it for the session."""
    return CardFacetsOut.model_validate(cards_service.card_facets(db))
