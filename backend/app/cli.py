"""Typer CLI. Every optimizer/ingest capability must be reachable here without the UI."""
import typer
from rich.console import Console

app = typer.Typer(help="binder-builder")
ingest_app = typer.Typer(help="Data ingestion")
sim_app = typer.Typer(help="Simulation and optimization")
sync_app = typer.Typer(help="Sync curated YAML into the database")
app.add_typer(ingest_app, name="ingest")
app.add_typer(sim_app, name="sim")
app.add_typer(sync_app, name="sync")

console = Console()


@ingest_app.command("cards")
def ingest_cards(set_id: str = typer.Option(None, "--set"), all_sets: bool = False) -> None:
    """Pull card metadata from pokemontcg.io."""
    raise NotImplementedError  # TODO(phase-1.2)


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
