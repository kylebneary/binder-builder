"""Collection CRUD. Plain dataclasses in/out -- see docs/01-architecture.md layer rules."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Collection, CollectionItem


@dataclass(slots=True)
class CollectionItemData:
    card_variant_id: int
    quantity: int = 1
    condition: str = "NM"
    language: str = "EN"
    is_graded: bool = False
    grader: str | None = None
    grade: str | None = None
    acquired_price: Decimal | None = None
    acquired_on: date | None = None
    storage_location: str | None = None
    notes: str | None = None


def get_or_create_default_collection(db: Session) -> Collection:
    row = db.execute(select(Collection).where(Collection.is_default.is_(True))).scalars().first()
    if row is not None:
        return row
    row = Collection(name="My Collection", is_default=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_collection_items(db: Session, collection_id: int) -> list[CollectionItem]:
    return list(
        db.execute(
            select(CollectionItem).where(CollectionItem.collection_id == collection_id)
        ).scalars()
    )


def upsert_collection_item(
    db: Session, collection_id: int, data: CollectionItemData
) -> CollectionItem:
    """Upsert a holding, keyed on the physical slot where one is known.

    `collection_item` is one row per physical card (see the model docstring), so identity is
    `(collection_id, storage_location)` whenever `data.storage_location` is set: the slot is the
    thing that is unique, and keying on it is what lets the same file be re-imported without
    duplicating every row. Fifteen copies of a card in fifteen slots are fifteen rows.

    Without a location there is nothing physical to key on, so this falls back to the old natural
    key -- (collection_id, card_variant_id, condition, language, is_graded, grade) -- and quantity
    carries the count. That is the right shape for a Collectr or Deckbox export, which knows you
    own four of a card but not where any of them sit.

    Setting quantity to 0 keeps the row (a deliberate zero-of-this-variant is different from never
    having recorded it) -- use delete_collection_item to actually remove a holding.
    """
    if data.storage_location is not None:
        key = (CollectionItem.storage_location == data.storage_location,)
    else:
        key = (
            CollectionItem.card_variant_id == data.card_variant_id,
            CollectionItem.condition == data.condition,
            CollectionItem.language == data.language,
            CollectionItem.is_graded == data.is_graded,
            CollectionItem.grade == data.grade,
            CollectionItem.storage_location.is_(None),
        )
    row = db.execute(
        select(CollectionItem).where(
            CollectionItem.collection_id == collection_id,
            *key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = CollectionItem(collection_id=collection_id)
        db.add(row)
    # Keyed by slot, the card in it can change when a collection is reorganised, so every field
    # is written on update rather than only at insert.
    row.card_variant_id = data.card_variant_id
    row.condition = data.condition
    row.language = data.language
    row.is_graded = data.is_graded
    row.grade = data.grade
    row.quantity = data.quantity
    row.grader = data.grader
    row.acquired_price = data.acquired_price
    row.acquired_on = data.acquired_on
    row.storage_location = data.storage_location
    row.notes = data.notes
    db.commit()
    db.refresh(row)
    return row


def delete_collection_item(db: Session, collection_id: int, item_id: int) -> bool:
    row = db.execute(
        select(CollectionItem).where(
            CollectionItem.id == item_id, CollectionItem.collection_id == collection_id
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
