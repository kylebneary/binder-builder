"""Adapter interfaces. Add a data source by implementing these, never by editing call sites."""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(slots=True)
class SetDTO:
    ptcg_set_id: str
    name: str
    series: str | None
    printed_total: int | None
    total: int | None
    release_date: date | None
    ptcgo_code: str | None
    symbol_url: str | None
    logo_url: str | None


@dataclass(slots=True)
class CardDTO:
    ptcg_card_id: str
    ptcg_set_id: str
    number: str
    name: str
    supertype: str | None
    rarity: str | None
    artist: str | None
    subtypes: list[str]
    types: list[str]
    national_pokedex_numbers: list[int]
    image_small: str | None
    image_large: str | None


@dataclass(slots=True)
class ProductDTO:
    """A tcgcsv product -- may be a single card or a sealed item.

    Sealed products are identified by the ABSENCE of Number/Rarity in extendedData.
    Do not classify on the product name; naming is inconsistent across eras.
    """

    tcgplayer_product_id: int
    tcgplayer_group_id: int
    name: str
    clean_name: str
    url: str | None
    image_url: str | None
    card_number: str | None
    rarity: str | None

    @property
    def is_sealed(self) -> bool:
        return self.card_number is None and self.rarity is None


@dataclass(slots=True)
class PricePointDTO:
    tcgplayer_product_id: int
    sub_type_name: str
    observed_on: date
    low: float | None
    mid: float | None
    high: float | None
    market: float | None
    direct_low: float | None
    source: str = "tcgcsv"
    currency: str = "USD"


class CardSource(Protocol):
    name: str

    def fetch_sets(self) -> Iterable[SetDTO]: ...
    def fetch_cards(self, set_ref: str) -> Iterable[CardDTO]: ...


class PriceSource(Protocol):
    name: str

    def fetch_prices(self, as_of: date) -> Iterable[PricePointDTO]: ...
