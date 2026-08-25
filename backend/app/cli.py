"""Typer CLI. Every optimizer/ingest capability must be reachable here without the UI."""

import typer
from rich.console import Console

from app.db import SessionLocal
from app.ingest.cards import ingest_sets_and_cards
from app.ingest.pokemontcg import PokemonTcgCardSource

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
    as_of: str = typer.Option(None, "--date"), backfill: bool = False
) -> None:
    """Pull daily prices from tcgcsv. tcgcsv publishes ~20:00 UTC; run this at 20:30."""
    raise NotImplementedError  # TODO(phase-1.4)


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
