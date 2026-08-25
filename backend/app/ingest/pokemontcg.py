"""pokemontcg.io v2 adapter -- card metadata.

Volunteer-run with occasional outages. Cache aggressively; card data changes only on set release.
"""
from collections.abc import Iterable

from app.ingest.base import CardDTO, SetDTO


class PokemonTcgCardSource:
    name = "pokemontcg"

    def fetch_sets(self) -> Iterable[SetDTO]:
        # TODO(phase-1.2): GET {base}/sets, paginate, map to SetDTO.
        raise NotImplementedError

    def fetch_cards(self, set_ref: str) -> Iterable[CardDTO]:
        # TODO(phase-1.2): GET {base}/cards?q=set.id:{set_ref}&pageSize=250, paginate.
        raise NotImplementedError
