"""pokemontcg.io v2 adapter -- offline fallback.

Same parsing as app.ingest.pokemontcg.PokemonTcgCardSource, but reads JSON saved by hand (e.g.
via `Invoke-WebRequest`/`curl` against the same endpoints) instead of calling the API directly.
For when the live API is down for a specific set across every retry -- see
scripts/import_offline_cards.py for the CLI wrapper.

Expects one or more `<prefix>_page<N>.json` files per resource, each the raw JSON body of a
`GET /v2/sets` or `GET /v2/cards?q=set.id:<id>` response (i.e. `{"data": [...], ...}`), saved
with any page size. Pages are concatenated in filename order; nothing here re-paginates for you.
"""
import json
import re
from collections.abc import Iterable
from pathlib import Path

from app.ingest.base import CardDTO, SetDTO
from app.ingest.pokemontcg import _parse_release_date


def _load_pages(directory: Path, prefix: str) -> list[dict]:
    pattern = re.compile(rf"^{re.escape(prefix)}_page(\d+)\.json$")
    matches = sorted(
        (p for p in directory.glob(f"{prefix}_page*.json") if pattern.match(p.name)),
        key=lambda p: int(pattern.match(p.name).group(1)),  # type: ignore[union-attr]
    )
    if not matches:
        raise FileNotFoundError(f"no {prefix}_page*.json files found in {directory}")
    items: list[dict] = []
    for path in matches:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.extend(payload.get("data") or [])
    return items


class OfflineCardSource:
    """Reads manually-downloaded pokemontcg.io JSON instead of hitting the API.

    `directory` must contain `sets_page<N>.json` (from `GET /v2/sets`) and, for each set you
    want cards for, `<ptcg_set_id>_page<N>.json` (from `GET /v2/cards?q=set.id:<ptcg_set_id>`).
    """

    name = "pokemontcg-offline"

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def fetch_sets(self) -> Iterable[SetDTO]:
        for raw in _load_pages(self.directory, "sets"):
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
        for raw in _load_pages(self.directory, set_ref):
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
