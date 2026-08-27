"""pokemontcg.io v2 adapter -- GitHub mirror fallback.

The `PokemonTCG/pokemon-tcg-data` repo (https://github.com/PokemonTCG/pokemon-tcg-data) publishes
the same card/set data the live API serves, as static JSON checked into git, one file per set at
`cards/en/<ptcg_set_id>.json` plus a combined `sets/en.json`. Use this when the live API
(`app.ingest.pokemontcg`) is hard-down for a specific set across retries -- see
docs/03-data-sources.md. Same DTO mapping as the live adapter; the only shape differences are that
the mirror's files are bare JSON arrays (no `{"data": [...]}` envelope, no pagination) and card
objects don't embed a `set` object, so `ptcg_set_id` falls back to the requested `set_ref`.
"""
import logging
from collections.abc import Iterable

import httpx

from app.config import get_settings
from app.ingest.base import CardDTO, SetDTO
from app.ingest.pokemontcg import _parse_release_date

log = logging.getLogger(__name__)


class PokemonTcgGithubMirrorClient:
    def __init__(self, base_url: str | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.pokemontcg_github_mirror_base_url).rstrip("/")
        self._client = httpx.Client(timeout=60.0, follow_redirects=True)

    def _get_json(self, path: str) -> list[dict]:
        r = self._client.get(f"{self.base_url}{path}")
        if r.status_code != 200:
            raise RuntimeError(
                f"pokemontcg-data mirror request failed: GET {r.request.url} -> "
                f"{r.status_code} {r.text[:500]}"
            )
        return r.json()

    def fetch_sets(self) -> list[dict]:
        return self._get_json("/sets/en.json")

    def fetch_cards(self, set_ref: str) -> list[dict]:
        return self._get_json(f"/cards/en/{set_ref}.json")

    def close(self) -> None:
        self._client.close()


class PokemonTcgGithubMirrorSource:
    name = "pokemontcg-github-mirror"

    def __init__(self, client: PokemonTcgGithubMirrorClient | None = None) -> None:
        self.client = client or PokemonTcgGithubMirrorClient()

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
