"""Typer CLI. Every optimizer/ingest capability must be reachable here without the UI."""

from datetime import date
from pathlib import Path

import typer
from rich.console import Console

from app.config import get_settings
from app.db import SessionLocal
from app.ingest.cards import ingest_sets_and_cards
from app.ingest.pokemontcg import PokemonTcgCardSource
from app.ingest.prices import ingest_group_prices, resolve_group_set_pairs
from app.ingest.sealed_map import (
    load_sealed_map,
    sync_sealed_map_to_db,
    unmapped_sealed_products,
)
from app.ingest.set_mapping import load_set_map, sync_set_map_to_db
from app.ingest.tcgcsv import TcgCsvPriceSource
from app.services.collection import get_or_create_default_collection
from app.services.csv_export import export_collection_csv
from app.services.csv_import import apply_import, dry_run_import, parse_csv

app = typer.Typer(help="binder-builder")
ingest_app = typer.Typer(help="Data ingestion")
sim_app = typer.Typer(help="Simulation and optimization")
sync_app = typer.Typer(help="Sync curated YAML into the database")
import_app = typer.Typer(help="Import collection data from other tools")
export_app = typer.Typer(help="Export collection data")
app.add_typer(ingest_app, name="ingest")
app.add_typer(sim_app, name="sim")
app.add_typer(sync_app, name="sync")
app.add_typer(import_app, name="import")
app.add_typer(export_app, name="export")

console = Console()


@ingest_app.command("cards")
def ingest_cards(
    set_id: list[str] | None = typer.Option(  # noqa: B008 -- required Typer pattern
        None, "--set", help="ptcg_set_id, e.g. sv8. Repeatable."
    ),
    all_sets: bool = typer.Option(False, "--all", help="Ingest every set from pokemontcg.io."),
) -> None:
    """Pull card metadata from pokemontcg.io."""
    if bool(set_id) == all_sets:
        console.print("[red]Pass exactly one of --set (repeatable) or --all.[/red]")
        raise typer.Exit(code=1)

    source = PokemonTcgCardSource()
    db = SessionLocal()
    try:
        results = ingest_sets_and_cards(db, source, None if all_sets else list(set_id or []))
    finally:
        source.client.close()
        db.close()

    failed = False
    for r in results:
        if r.error:
            failed = True
            console.print(f"[red]{r.ptcg_set_id}: FAILED -- {r.error}[/red]")
        else:
            console.print(f"{r.ptcg_set_id}: {r.n_cards} cards")
    if failed:
        raise typer.Exit(code=1)


@ingest_app.command("prices")
def ingest_prices(
    group: list[int] | None = typer.Option(  # noqa: B008 -- required Typer pattern
        None, "--group", help="tcgcsv groupId. Repeatable."
    ),
    set_id: list[str] | None = typer.Option(  # noqa: B008 -- required Typer pattern
        None,
        "--set",
        help=(
            "ptcg_set_id. Repeatable. Pair 1:1 with --group to declare that a groupId is that "
            "set (persists Set.tcgplayer_group_id); use alone if already linked."
        ),
    ),
    as_of: str | None = typer.Option(
        None,
        "--date",
        help=(
            "Stamp price_point.observed_on with this date (YYYY-MM-DD), default today. tcgcsv "
            "only exposes current prices, so this changes what's recorded, not what's fetched."
        ),
    ),
    backfill: bool = typer.Option(False, "--backfill", help="Pull archived historical bundles."),
) -> None:
    """Pull daily prices from tcgcsv. tcgcsv publishes ~20:00 UTC; run this at 20:30."""
    if backfill:
        console.print(
            "[red]--backfill is not implemented: docs/03-data-sources.md mentions archived "
            "daily bundles exist but doesn't give a URL pattern or schema to fetch them from, "
            "so this isn't guessed at. Use --date to backfill by hand from a known snapshot "
            "instead.[/red]"
        )
        raise typer.Exit(code=1)

    observed_on = date.fromisoformat(as_of) if as_of else date.today()

    source = TcgCsvPriceSource()
    db = SessionLocal()
    try:
        try:
            pairs = resolve_group_set_pairs(
                db, group, set_id, lambda: [g["groupId"] for g in source.client.fetch_groups()]
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        if not group and not set_id:
            console.print(
                f"[yellow]No --group/--set filter given: pulling all {len(pairs)} tcgcsv "
                "groups (~20-40MB). Pass --group/--set to limit this.[/yellow]"
            )

        results = ingest_group_prices(db, source, observed_on, pairs)
    finally:
        source.client.close()
        db.close()

    failed = False
    for r in results:
        if r.error:
            failed = True
            console.print(f"[red]group {r.group_id}: FAILED -- {r.error}[/red]")
        else:
            note = "" if r.matched else " (no linked Set -- card_variant matching skipped)"
            console.print(
                f"group {r.group_id}: {r.n_price_points} price points, "
                f"{r.n_card_variants} card_variant rows, "
                f"{r.n_sealed_products} new sealed_product rows{note}"
            )
    if failed:
        raise typer.Exit(code=1)


@sync_app.command("setmap")
def sync_setmap(
    path: str | None = typer.Option(
        None, "--path", help="Path to the set map YAML (default: data/set_map.yaml)."
    ),
) -> None:
    """Load data/set_map.yaml into Set.tcgplayer_group_id. Idempotent; the YAML is the source
    of truth (see scripts/build_set_map.py to seed/extend it)."""
    map_path = Path(path) if path else get_settings().set_map_path
    mapping = load_set_map(map_path)
    if not mapping:
        console.print(f"[yellow]{map_path} is empty or missing -- nothing to sync.[/yellow]")
        return

    db = SessionLocal()
    try:
        results = sync_set_map_to_db(db, mapping)
    finally:
        db.close()

    missing = [r for r in results if r.status == "no_set_row"]
    for r in results:
        if r.status != "no_set_row":
            console.print(f"{r.ptcg_set_id}: group {r.tcgplayer_group_id} ({r.status})")
    if missing:
        ids = ", ".join(r.ptcg_set_id for r in missing)
        console.print(
            f"[yellow]{len(missing)} set(s) in {map_path} have no Set row yet -- run "
            f"`bb ingest cards --set <id>` first: {ids}[/yellow]"
        )


@sync_app.command("sealedmap")
def sync_sealedmap(
    path: str | None = typer.Option(
        None, "--path", help="Path to the sealed map YAML (default: data/sealed_map.yaml)."
    ),
) -> None:
    """Load data/sealed_map.yaml into sealed_product rows. Idempotent; the YAML is the sole
    source of truth for product_type/packs_per_unit -- entirely hand-curated, since neither can
    be reliably parsed from tcgcsv product names (see app/ingest/sealed_map.py)."""
    map_path = Path(path) if path else get_settings().sealed_map_path
    mapping = load_sealed_map(map_path)

    db = SessionLocal()
    try:
        results = sync_sealed_map_to_db(db, mapping) if mapping else []
        review_queue = unmapped_sealed_products(db, mapping)
    finally:
        db.close()

    missing = [r for r in results if r.status == "no_product_row"]
    for r in results:
        if r.status != "no_product_row":
            console.print(f"product {r.tcgplayer_product_id}: {r.status}")
    if missing:
        ids = ", ".join(str(r.tcgplayer_product_id) for r in missing)
        console.print(
            f"[yellow]{len(missing)} product(s) in {map_path} have no sealed_product row yet "
            f"-- run `bb ingest prices` for that set first: {ids}[/yellow]"
        )
    if review_queue:
        console.print(
            f"[yellow]{len(review_queue)} sealed product(s) need classification in "
            f"{map_path} (currently product_type=OTHER, packs_per_unit=null):[/yellow]"
        )
        for p in review_queue:
            console.print(f"  {p.tcgplayer_product_id}: {p.name!r}")


@sync_app.command("pullrates")
def sync_pullrates() -> None:
    """Load data/pull_rates/*.yaml into the DB. Idempotent. Fails loudly on invalid profiles."""
    raise NotImplementedError  # TODO(phase-2.4)


@import_app.command("csv")
def import_csv(
    path: str,
    apply: bool = typer.Option(
        False, "--apply", help="Write to the DB. Default is a dry run: report only, no writes."
    ),
) -> None:
    """Import a Collectr / TCG Collector / Deckbox CSV export.

    Column detection is a best-effort alias table, NOT verified against a real export from any
    of these three tools (see app/services/csv_import.py) -- always check the printed column
    mapping and the dry-run diff before trusting an --apply run.
    """
    content = Path(path).read_text(encoding="utf-8")
    columns, rows = parse_csv(content)
    console.print(f"Detected columns: {columns}")
    if not rows:
        console.print("[yellow]No data rows found.[/yellow]")
        return

    db = SessionLocal()
    try:
        results = apply_import(db, rows) if apply else dry_run_import(db, rows)
    finally:
        db.close()

    matched = [r for r in results if r.status == "matched"]
    problems = [r for r in results if r.status != "matched"]
    verb = "written" if apply else "would be written (dry run -- pass --apply to write)"
    console.print(f"{len(matched)} / {len(results)} rows matched, {verb}")
    for r in problems:
        console.print(f"[yellow]line {r.line_number}: {r.status} -- {r.detail}[/yellow]")


@export_app.command("csv")
def export_csv(path: str) -> None:
    """Export the default collection to CSV."""
    db = SessionLocal()
    try:
        collection = get_or_create_default_collection(db)
        content = export_collection_csv(db, collection.id)
    finally:
        db.close()
    Path(path).write_text(content)
    console.print(f"Wrote {path}")


@sim_app.command("run")
def sim_run(
    goal_id: int,
    trials: int = 20_000,
    objective: str = "min_expected_cost",
    seed: int = 0,
) -> None:
    """Optimize a completion goal and print the ranked strategies."""
    raise NotImplementedError  # TODO(phase-2.10)


if __name__ == "__main__":
    app()
