"""tcgcsv.com adapter -- the primary price source.

Publishes once daily around 20:00 UTC. Do not poll more often than that.
Schemas verified live 2026-08-25; see docs/03-data-sources.md.
"""
import logging
from collections.abc import Iterable, Iterator
from datetime import date

import httpx

from app.config import get_settings
from app.ingest.base import PricePointDTO, ProductDTO

log = logging.getLogger(__name__)


class TcgCsvClient:
    def __init__(self, base_url: str | None = None, category_id: int | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.tcgcsv_base_url).rstrip("/")
        self.category_id = category_id or s.tcgcsv_pokemon_category_id
        self._client = httpx.Client(timeout=60.0, follow_redirects=True)

    def _get(self, path: str) -> list[dict]:
        url = f"{self.base_url}{path}"
        r = self._client.get(url)
        r.raise_for_status()
        payload = r.json()
        # tcgcsv wraps list payloads; tolerate both shapes.
        if isinstance(payload, dict):
            return payload.get("results") or payload.get("data") or []
        return payload

    def fetch_groups(self) -> list[dict]:
        """Groups are sets/product lines. Fields: groupId, name, abbreviation,
        isSupplemental, publishedOn, modifiedOn, categoryId."""
        return self._get(f"/tcgplayer/{self.category_id}/groups")

    def fetch_products(self, group_id: int) -> Iterator[ProductDTO]:
        for raw in self._get(f"/tcgplayer/{self.category_id}/{group_id}/products"):
            ext = {e["name"]: e.get("value") for e in raw.get("extendedData") or []}
            yield ProductDTO(
                tcgplayer_product_id=raw["productId"],
                tcgplayer_group_id=raw["groupId"],
                name=raw["name"],
                clean_name=raw.get("cleanName") or raw["name"],
                url=raw.get("url"),
                image_url=raw.get("imageUrl"),
                card_number=ext.get("Number"),
                rarity=ext.get("Rarity"),
            )

    def fetch_group_prices(self, group_id: int, as_of: date) -> Iterator[PricePointDTO]:
        """One record per (productId, subTypeName). Nulls are common -- handle them."""
        for raw in self._get(f"/tcgplayer/{self.category_id}/{group_id}/prices"):
            yield PricePointDTO(
                tcgplayer_product_id=raw["productId"],
                sub_type_name=raw.get("subTypeName") or "Normal",
                observed_on=as_of,
                low=raw.get("lowPrice"),
                mid=raw.get("midPrice"),
                high=raw.get("highPrice"),
                market=raw.get("marketPrice"),
                direct_low=raw.get("directLowPrice"),
            )

    def close(self) -> None:
        self._client.close()


class TcgCsvPriceSource:
    name = "tcgcsv"

    def __init__(self, client: TcgCsvClient | None = None) -> None:
        self.client = client or TcgCsvClient()

    def fetch_prices(self, as_of: date) -> Iterable[PricePointDTO]:
        # TODO(phase-1.4): iterate only groups we have mapped in data/set_map.yaml,
        # not all 218 -- a full pull is 20-40MB and mostly irrelevant to the user's sets.
        for group in self.client.fetch_groups():
            yield from self.client.fetch_group_prices(group["groupId"], as_of)
