"""Typer CLI. Every optimizer/ingest capability must be reachable here without the UI."""

from datetime import date

import typer
from rich.console import Console

from app.db import SessionLocal
from app.ingest.cards import ingest_sets_and_cards
from app.ingest.pokemontcg import PokemonTcgCardSource
from app.ingest.prices import ingest_group_prices, resolve_group_set_pairs
from app.ingest.tcgcsv import TcgCsvPriceSource

app = typer.Typer(help="binder-builder")
ingest_app = typer.Typer(help="Data ingestion")
sim_app = typer.Typer(help="Simulation and optimization")
sync_app = typer.Typer(help="Sync curated YAML into the database")
app.add_typer(ingest_app, name="ingest")
app.add_typer(sim_app, name="sim")
app.add_typer(sync_app, name="sync")

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
                f"{r.n_card_variants} card_variant rows{note}"
            )
    if failed:
        raise typer.Exit(code=1)


@sync_app.command("pullrates")
def sync_pullrates() -> None:
    """Load data/pull_rates/*.yaml into the DB. Idempotent. Fails loudly on invalid profiles."""
    raise NotImplementedError  # TODO(phase-2.4)


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
