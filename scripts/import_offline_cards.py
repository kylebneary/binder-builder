#!/usr/bin/env python3
"""Fallback for when `bb ingest cards --set <id>` keeps failing against a flaky pokemontcg.io.

Loads card metadata from JSON files saved by hand instead of calling the live API. See
backend/app/ingest/pokemontcg_offline.py for the exact file layout expected in --dir (default
data/manual_cards/): sets_page<N>.json plus <ptcg_set_id>_page<N>.json per set.

Usage: python scripts/import_offline_cards.py --set sv1 --set smp [--dir data/manual_cards]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import SessionLocal
from app.ingest.cards import ingest_sets_and_cards
from app.ingest.pokemontcg_offline import OfflineCardSource


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--set", dest="sets", action="append", required=True, help="ptcg_set_id, repeatable"
    )
    parser.add_argument(
        "--dir", default="data/manual_cards", help="directory with the saved JSON"
    )
    args = parser.parse_args()

    source = OfflineCardSource(Path(args.dir))
    db = SessionLocal()
    try:
        results = ingest_sets_and_cards(db, source, args.sets)
    finally:
        db.close()

    failed = False
    for r in results:
        if r.error:
            failed = True
            print(f"{r.ptcg_set_id}: FAILED -- {r.error}")
        else:
            print(f"{r.ptcg_set_id}: {r.n_cards} cards")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
