"""pokemontcg.io v2 adapter -- card metadata.

Volunteer-run with occasional outages. Cache aggressively; card data changes only on set release.
"""
import logging
from collections.abc import Iterable, Iterator
from datetime import date, datetime

import httpx

from app.config import get_settings
from app.ingest.base import CardDTO, SetDTO

log = logging.getLogger(__name__)

PAGE_SIZE = 250


def _parse_release_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return datetime.strptime(raw, "%Y/%m/%d").date()


class PokemonTcgClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.pokemontcg_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else s.pokemontcg_api_key
        headers = {"X-Api-Key": self.api_key} if self.api_key else {}
        self._client = httpx.Client(timeout=60.0, follow_redirects=True, headers=headers)

    def _get_paginated(self, path: str, params: dict) -> Iterator[dict]:
        page = 1
        while True:
            r = self._client.get(
                f"{self.base_url}{path}", params={**params, "page": page, "pageSize": PAGE_SIZE}
            )
            if r.status_code != 200:
                raise RuntimeError(
                    f"pokemontcg.io request failed: GET {r.request.url} -> "
                    f"{r.status_code} {r.text[:500]}"
                )
            payload = r.json()
            results = payload.get("data") or []
            yield from results
            if len(results) < PAGE_SIZE:
                return
            page += 1

    def fetch_sets(self) -> Iterator[dict]:
        yield from self._get_paginated("/sets", {})

    def fetch_cards(self, set_ref: str) -> Iterator[dict]:
        yield from self._get_paginated("/cards", {"q": f"set.id:{set_ref}"})

    def close(self) -> None:
        self._client.close()


class PokemonTcgCardSource:
    name = "pokemontcg"

    def __init__(self, client: PokemonTcgClient | None = None) -> None:
        self.client = client or PokemonTcgClient()

    def fetch_sets(self) -> Iterable[SetDTO]:
        for raw in self.client.fetch_sets():
            images = raw.get("images") or {}
            yield SetDTO(
                ptcg_set_id=raw["id"],
                name=raw["name"],
                series=raw.get("series"),
                printed_total=raw.get("printedTotal"),
                total=raw.get("total"),
                release_date=_parse_release_date(raw.get("releaseDate")),
                ptcgo_code=raw.get("ptcgoCode"),
                symbol_url=images.get("symbol"),
                logo_url=images.get("logo"),
            )

    def fetch_cards(self, set_ref: str) -> Iterable[CardDTO]:
        for raw in self.client.fetch_cards(set_ref):
            images = raw.get("images") or {}
            set_info = raw.get("set") or {}
            yield CardDTO(
                ptcg_card_id=raw["id"],
                ptcg_set_id=set_info.get("id", set_ref),
                number=raw["number"],
                name=raw["name"],
                supertype=raw.get("supertype"),
                rarity=raw.get("rarity"),
                artist=raw.get("artist"),
                subtypes=raw.get("subtypes") or [],
                types=raw.get("types") or [],
                national_pokedex_numbers=raw.get("nationalPokedexNumbers") or [],
                image_small=images.get("small"),
                image_large=images.get("large"),
            )
