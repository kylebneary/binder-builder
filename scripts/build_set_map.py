#!/usr/bin/env python3
"""One-off maintenance script (phase 1.5): fuzzy-match pokemontcg.io sets to tcgcsv groups and
seed data/set_map.yaml.

Never overwrites an existing entry -- a set already in the file (including a hand-correction)
is left alone; only new keys are added. Anything not matched with confidence is printed as a
review report so it can be hand-added.

Usage: python scripts/build_set_map.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.ingest.pokemontcg import PokemonTcgCardSource
from app.ingest.set_mapping import match_sets, merge_set_map
from app.ingest.tcgcsv import TcgCsvClient

SET_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "set_map.yaml"


def main() -> None:
    card_source = PokemonTcgCardSource()
    tcgcsv_client = TcgCsvClient()
    try:
        print("Fetching pokemontcg.io sets...")
        ptcg_sets = list(card_source.fetch_sets())
        print(f"  {len(ptcg_sets)} sets")

        print("Fetching tcgcsv groups...")
        groups = tcgcsv_client.fetch_groups()
        print(f"  {len(groups)} groups")
    finally:
        card_source.client.close()
        tcgcsv_client.close()

    results = match_sets(ptcg_sets, groups)
    matched = {
        r.ptcg_set_id: r.tcgplayer_group_id for r in results if r.tcgplayer_group_id is not None
    }
    unmatched = [r for r in results if r.tcgplayer_group_id is None]

    before = len(matched)
    merged = merge_set_map(SET_MAP_PATH, matched)
    print(f"\n{before} sets matched this run; {SET_MAP_PATH} now has {len(merged)} entries total.")

    if unmatched:
        print(f"\n{len(unmatched)} sets need manual review (no confident tcgcsv match):")
        for r in sorted(unmatched, key=lambda r: r.ptcg_set_id):
            print(f"  {r.ptcg_set_id}: {r.reason}")
        print(f"\nHand-add these to {SET_MAP_PATH} once you've identified the right groupId --")
        print("browse https://tcgcsv.com/tcgplayer/3/groups to find it.")


if __name__ == "__main__":
    main()
