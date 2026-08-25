"""Pydantic request/response models. Routers only -- services stay Pydantic-free so they're
reusable from the CLI (see docs/01-architecture.md)."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    variant: str
    tcgplayer_product_id: int | None
    tcgplayer_sub_type_name: str | None
    is_canonical: bool
    market_price: Decimal | None
    owned_quantity: int


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ptcg_card_id: str
    number: str
    number_sort: int
    name: str
    supertype: str | None
    rarity: str | None
    artist: str | None
    image_small: str | None
    image_large: str | None
    variants: list[VariantOut]
    is_owned: bool


class SetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ptcg_set_id: str
    name: str
    series: str | None
    printed_total: int | None
    total: int | None
    release_date: date | None
    symbol_url: str | None
    logo_url: str | None


class SetDetailOut(SetOut):
    cards: list[CardOut]
    owned_count: int
    needed_count: int


class CollectionItemIn(BaseModel):
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


class CollectionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    collection_id: int
    card_variant_id: int
    quantity: int
    condition: str
    language: str
    is_graded: bool
    grader: str | None
    grade: str | None
    acquired_price: Decimal | None
    acquired_on: date | None
    storage_location: str | None
    notes: str | None


class PortfolioValuePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observed_on: str
    total_market_value: Decimal


class PortfolioSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    collection_id: int
    total_market_value: Decimal
    total_cost_basis: Decimal
    unrealized_gain: Decimal
    item_count: int
    priced_item_count: int
    price_date: str | None


class GoalIn(BaseModel):
    name: str
    goal_type: str
    set_id: int | None = None
    filter_json: dict | None = None
    target_condition: str = "NM"


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    goal_type: str
    set_id: int | None
    filter_json: dict | None
    target_condition: str


class NeedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    card_variant_id: int
    card_name: str
    number: str
    rarity: str | None
    variant: str
    required_qty: int
    owned_qty: int
    need_qty: int
    market_price: Decimal | None


class SinglesCostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    n_cards: int
    subtotal: Decimal
    orders: int
    shipping: Decimal
    tax: Decimal
    total: Decimal


class GoalDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    goal_type: str
    set_id: int | None
    target_condition: str
    items: list[NeedItemOut]
    cost: SinglesCostOut
    unpriced_count: int
