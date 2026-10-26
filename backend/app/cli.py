"""Typer CLI. Every optimizer/ingest capability must be reachable here without the UI."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from sqlalchemy import func, select

from app.binder.export import ExportError
from app.binder.layout import AutoLayoutMode
from app.binder.michi import ClusterKey, ScoreWeights
from app.config import get_settings
from app.db import SessionLocal
from app.ingest.cards import ingest_sets_and_cards
from app.ingest.pokemontcg import PokemonTcgCardSource
from app.ingest.pokemontcg_github import PokemonTcgGithubMirrorSource
from app.ingest.prices import ingest_group_prices, resolve_group_set_pairs
from app.ingest.pullrates import load_pull_rate_profiles, sync_pull_rates_to_db
from app.ingest.sealed_map import (
    load_sealed_map,
    sync_sealed_map_to_db,
    unmapped_sealed_products,
)
from app.ingest.set_mapping import load_set_map, sync_set_map_to_db
from app.ingest.tcgcsv import TcgCsvPriceSource
from app.models import GoalItem, SealedProduct
from app.models import Set as SetModel
from app.models.enums import GoalType
from app.services import binder as binder_service
from app.services import goals as goals_service
from app.services.binder import BinderData, LayoutError
from app.services.binder_export import (
    export_binder_inserts_pdf,
    export_binder_spread_png,
)
from app.services.cards import CardQuery, card_facets, search_cards, variant_ids
from app.services.collection import get_or_create_default_collection
from app.services.csv_export import export_collection_csv
from app.services.csv_import import apply_import, dry_run_import, parse_csv
from app.services.goals import GoalEditError
from app.services.inserts import InsertError, list_inserts, save_insert
from app.services.michi import apply_michi_layout, extract_colors
from app.services.simulation_runs import run_search_and_cache
from app.sim.optimizer import Objective
from app.sim.types import CostParams

app = typer.Typer(help="binder-builder")
ingest_app = typer.Typer(help="Data ingestion")
sim_app = typer.Typer(help="Simulation and optimization")
sync_app = typer.Typer(help="Sync curated YAML into the database")
import_app = typer.Typer(help="Import collection data from other tools")
export_app = typer.Typer(help="Export collection data")
goal_app = typer.Typer(help="Completion goals")
binder_app = typer.Typer(help="Binder designer")
cards_app = typer.Typer(help="Search the card catalogue")
app.add_typer(ingest_app, name="ingest")
app.add_typer(sim_app, name="sim")
app.add_typer(sync_app, name="sync")
app.add_typer(import_app, name="import")
app.add_typer(export_app, name="export")
app.add_typer(goal_app, name="goal")
app.add_typer(binder_app, name="binder")
app.add_typer(cards_app, name="cards")

console = Console()


@ingest_app.command("cards")
def ingest_cards(
    set_id: list[str] | None = typer.Option(
        None, "--set", help="ptcg_set_id, e.g. sv8. Repeatable."
    ),
    all_sets: bool = typer.Option(False, "--all", help="Ingest every set from pokemontcg.io."),
    source_name: str = typer.Option(
        "pokemontcg",
        "--source",
        help=(
            "Card metadata source: 'pokemontcg' (live API, default) or 'github-mirror' "
            "(PokemonTCG/pokemon-tcg-data GitHub mirror -- use when the live API is hard-down "
            "for a set, see docs/03-data-sources.md)."
        ),
    ),
) -> None:
    """Pull card metadata from pokemontcg.io."""
    if bool(set_id) == all_sets:
        console.print("[red]Pass exactly one of --set (repeatable) or --all.[/red]")
        raise typer.Exit(code=1)

    if source_name == "pokemontcg":
        source: PokemonTcgCardSource | PokemonTcgGithubMirrorSource = PokemonTcgCardSource()
    elif source_name == "github-mirror":
        source = PokemonTcgGithubMirrorSource()
    else:
        console.print(
            f"[red]Unknown --source {source_name!r}. Use 'pokemontcg' or 'github-mirror'.[/red]"
        )
        raise typer.Exit(code=1)
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
    group: list[int] | None = typer.Option(
        None, "--group", help="tcgcsv groupId. Repeatable."
    ),
    set_id: list[str] | None = typer.Option(
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
    pull_rates_dir = get_settings().pull_rates_dir
    profiles = load_pull_rate_profiles(pull_rates_dir)
    if not profiles:
        console.print(
            f"[yellow]No loadable profiles in {pull_rates_dir} -- nothing to sync.[/yellow]"
        )
        return

    db = SessionLocal()
    try:
        results = sync_pull_rates_to_db(db, profiles)
    finally:
        db.close()

    failed = False
    for r in results:
        if r.status.startswith("invalid") or r.status == "no_set_row":
            failed = True
            console.print(f"[red]{r.ptcg_set_id}: {r.status}[/red]")
        else:
            console.print(f"{r.ptcg_set_id}: {r.status}")
    if failed:
        raise typer.Exit(code=1)


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


@cards_app.command("search")
def cards_search(
    name: str | None = typer.Option(None, "--name", help="Substring of the card name."),
    sets: list[str] = typer.Option([], "--set", help="ptcg_set_id; repeat for several."),
    series: list[str] = typer.Option([], "--series", help="e.g. 'Scarlet & Violet'."),
    rarities: list[str] = typer.Option([], "--rarity", help="Exact rarity; repeatable."),
    supertypes: list[str] = typer.Option([], "--supertype", help="Pokémon | Trainer | Energy"),
    types: list[str] = typer.Option([], "--type", help="Energy type, e.g. Fire; repeatable."),
    subtypes: list[str] = typer.Option([], "--subtype", help="e.g. ex, VMAX, Supporter."),
    artists: list[str] = typer.Option([], "--artist", help="Exact illustrator name."),
    pokemon: list[str] = typer.Option(
        [], "--pokemon", help="Species name, matched by Pokédex number: Pikachu, not 'Pikachu ex'."
    ),
    dex: list[int] = typer.Option([], "--dex", help="National Pokédex number; repeatable."),
    variants: list[str] = typer.Option([], "--variant", help="e.g. reverse_holofoil."),
    all_printings: bool = typer.Option(
        False, "--all-printings", help="Every printing, not one per card (master-set style)."
    ),
    owned: str | None = typer.Option(None, "--owned", help="owned | missing"),
    min_price: str | None = typer.Option(None, "--min-price"),
    max_price: str | None = typer.Option(None, "--max-price"),
    year_from: int | None = typer.Option(None, "--year-from"),
    year_to: int | None = typer.Option(None, "--year-to"),
    sort: str = typer.Option("newest", "--sort", help="newest | oldest | name | price"),
    limit: int = typer.Option(50, "--limit", help="Cards to print."),
    save_goal: str | None = typer.Option(
        None, "--save-goal", help="Save the matches as a new goal with this name."
    ),
    live: bool = typer.Option(
        False,
        "--live",
        help="With --save-goal: store the filter itself, so the goal picks up newly ingested "
        "cards. Default is a fixed list you can then edit card by card.",
    ),
    add_to_goal: int | None = typer.Option(
        None, "--add-to-goal", help="Add every match to this custom goal."
    ),
) -> None:
    """Search the whole catalogue by any combination of attributes."""
    if owned not in (None, "owned", "missing"):
        console.print("[red]--owned takes 'owned' or 'missing'.[/red]")
        raise typer.Exit(code=1)
    if sort not in ("newest", "oldest", "name", "price"):
        console.print("[red]--sort takes newest, oldest, name or price.[/red]")
        raise typer.Exit(code=1)

    db = SessionLocal()
    try:
        set_ids: list[int] = []
        for code in sets:
            row = db.execute(
                select(SetModel).where(SetModel.ptcg_set_id == code)
            ).scalar_one_or_none()
            if row is None:
                console.print(f"[red]No set with ptcg_set_id {code!r}.[/red]")
                raise typer.Exit(code=1)
            set_ids.append(row.id)

        dex_numbers = list(dex)
        if pokemon:
            by_name = {s.name.lower(): s.pokedex_number for s in card_facets(db).species}
            for species in pokemon:
                number = by_name.get(species.lower())
                if number is None:
                    console.print(
                        f"[red]No species named {species!r}. Use the bare species name "
                        "(Charizard, not Charizard ex), or --name for a substring.[/red]"
                    )
                    raise typer.Exit(code=1)
                dex_numbers.append(number)

        query = CardQuery(
            q=name,
            set_ids=set_ids,
            series=series,
            rarities=rarities,
            supertypes=supertypes,
            types=types,
            subtypes=subtypes,
            artists=artists,
            pokedex_numbers=dex_numbers,
            variants=variants,
            variant_scope="all" if all_printings else "canonical",
            owned=owned,  # type: ignore[arg-type]
            min_price=Decimal(min_price) if min_price else None,
            max_price=Decimal(max_price) if max_price else None,
            year_from=year_from,
            year_to=year_to,
        )
        collection = get_or_create_default_collection(db)
        result = search_cards(
            db, query, collection_id=collection.id, sort=sort, limit=limit  # type: ignore[arg-type]
        )
        for card in result.cards:
            prices = [v.market_price for v in card.variants if v.market_price is not None]
            price = f"${max(prices)}" if prices else "no price"
            mark = "[green]owned[/green]" if card.is_owned else ""
            console.print(
                f"  {card.ptcg_set_id:>10} {card.number:>6}  {card.name} "
                f"({card.rarity or '-'}) -- {price} {mark}"
            )
        console.print(f"{result.total} matching cards (showing {len(result.cards)}).")
        if result.unplaceable_count:
            console.print(
                f"[yellow]{result.unplaceable_count} more match but have no printing row, so "
                "they cannot go in a goal or a binder -- run `alembic upgrade head` or re-ingest "
                "their sets' cards to give them an unpriced placeholder.[/yellow]"
            )

        if save_goal:
            try:
                if live:
                    goal = goals_service.create_goal(
                        db, save_goal, GoalType.FILTER, filter_json=query.to_goal_filter()
                    )
                else:
                    ids = variant_ids(db, query, collection_id=collection.id)
                    goal = goals_service.create_goal(
                        db, save_goal, GoalType.CUSTOM, card_variant_ids=ids
                    )
            except GoalEditError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=1) from None
            console.print(f"Created goal {goal.id}: {goal.name!r} ({goal.goal_type})")
        if add_to_goal is not None:
            ids = variant_ids(db, query, collection_id=collection.id)
            try:
                edit = goals_service.edit_goal_items(db, add_to_goal, add=ids)
            except GoalEditError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=1) from None
            if edit is None:
                console.print(f"[red]No goal with id {add_to_goal}.[/red]")
                raise typer.Exit(code=1)
            console.print(
                f"Added {edit.added} to goal {add_to_goal}; it now holds {edit.item_count}."
            )
    finally:
        db.close()


@goal_app.command("create")
def goal_create(
    name: str = typer.Option(..., "--name", help="Human-readable goal name."),
    goal_type: str = typer.Option(
        "set", "--type", help="set | master_set | grand_master_set | custom"
    ),
    set_id: str | None = typer.Option(None, "--set", help="ptcg_set_id, e.g. sv8."),
    start_with: list[int] = typer.Option(
        [], "--variant", help="Custom goals: a card_variant id to start with; repeatable."
    ),
) -> None:
    """Create a completion goal and materialise its need list.

    For filter goals ("every Pikachu", "every card by an artist") use
    `bb cards search ... --save-goal NAME --live`, which takes every search filter.
    """
    try:
        parsed_type = GoalType(goal_type)
    except ValueError:
        console.print(f"[red]Unknown goal type {goal_type!r}.[/red]")
        raise typer.Exit(code=1) from None
    if parsed_type == GoalType.FILTER:
        console.print(
            "[red]Create filter goals with `bb cards search <filters> --save-goal NAME --live`."
            "[/red]"
        )
        raise typer.Exit(code=1)

    db = SessionLocal()
    try:
        if parsed_type == GoalType.CUSTOM:
            try:
                goal = goals_service.create_goal(
                    db, name=name, goal_type=parsed_type, card_variant_ids=start_with
                )
            except GoalEditError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=1) from None
            console.print(f"Created goal {goal.id}: {goal.name!r} ({goal.goal_type})")
            return

        if set_id is None:
            console.print("[red]Set goals need --set.[/red]")
            raise typer.Exit(code=1)
        set_row = db.execute(
            select(SetModel).where(SetModel.ptcg_set_id == set_id)
        ).scalar_one_or_none()
        if set_row is None:
            console.print(
                f"[red]No set with ptcg_set_id={set_id!r} -- "
                f"run `bb ingest cards --set {set_id}` first.[/red]"
            )
            raise typer.Exit(code=1)
        goal = goals_service.create_goal(db, name=name, goal_type=parsed_type, set_id=set_row.id)
        console.print(f"Created goal {goal.id}: {goal.name!r} ({goal.goal_type})")
    finally:
        db.close()


def _edit_goal(goal_id: int, add: list[int], remove: list[int]) -> None:
    db = SessionLocal()
    try:
        edit = goals_service.edit_goal_items(db, goal_id, add=add, remove=remove)
    except GoalEditError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    finally:
        db.close()
    if edit is None:
        console.print(f"[red]No goal with id {goal_id}.[/red]")
        raise typer.Exit(code=1)
    console.print(
        f"Added {edit.added}, removed {edit.removed}; goal {goal_id} now holds {edit.item_count}."
    )


@goal_app.command("add-cards")
def goal_add_cards(
    goal_id: int,
    variants: list[int] = typer.Option(..., "--variant", help="card_variant id; repeatable."),
) -> None:
    """Add cards to a custom goal. `bb cards search ... --add-to-goal ID` adds by filter."""
    _edit_goal(goal_id, variants, [])


@goal_app.command("remove-cards")
def goal_remove_cards(
    goal_id: int,
    variants: list[int] = typer.Option(..., "--variant", help="card_variant id; repeatable."),
) -> None:
    """Remove cards from a custom goal."""
    _edit_goal(goal_id, [], variants)


@goal_app.command("convert")
def goal_convert(goal_id: int) -> None:
    """Freeze a set or filter goal into a custom goal, so its cards can be edited by hand."""
    db = SessionLocal()
    try:
        goal = goals_service.convert_to_custom(db, goal_id)
    finally:
        db.close()
    if goal is None:
        console.print(f"[red]No goal with id {goal_id}.[/red]")
        raise typer.Exit(code=1)
    console.print(f"Goal {goal_id} is now a custom goal.")


@goal_app.command("resync")
def goal_resync(goal_id: int) -> None:
    """Re-run a set or filter goal's rule, e.g. after ingesting a new set."""
    db = SessionLocal()
    try:
        goal = goals_service.resync_goal(db, goal_id)
        count = db.execute(
            select(func.count(GoalItem.id)).where(GoalItem.goal_id == goal_id)
        ).scalar_one()
    finally:
        db.close()
    if goal is None:
        console.print(f"[red]No goal with id {goal_id}.[/red]")
        raise typer.Exit(code=1)
    console.print(f"Goal {goal_id} ({goal.goal_type}) holds {count} cards.")


@goal_app.command("need-list")
def goal_need_list(goal_id: int) -> None:
    """Print a goal's need list and its plain singles cost."""
    db = SessionLocal()
    try:
        collection = get_or_create_default_collection(db)
        detail = goals_service.get_goal_need_list(db, goal_id, collection.id)
    finally:
        db.close()

    if detail is None:
        console.print(f"[red]No goal with id {goal_id}.[/red]")
        raise typer.Exit(code=1)

    console.print(f"Goal {detail.id}: {detail.name!r} ({detail.goal_type})")
    needed = [i for i in detail.items if i.need_qty > 0]
    for item in needed:
        price = f"${item.market_price}" if item.market_price is not None else "no price"
        console.print(
            f"  {item.number} {item.card_name} ({item.variant}) x{item.need_qty} -- {price}"
        )
    console.print(
        f"{detail.cost.n_cards} cards needed, {detail.unpriced_count} unpriced -- "
        f"subtotal ${detail.cost.subtotal}, {detail.cost.orders} orders, "
        f"shipping ${detail.cost.shipping}, total ${detail.cost.total}"
    )


@goal_app.command("export-mass-entry")
def goal_export_mass_entry(
    goal_id: int,
    path: str | None = typer.Option(
        None, "--path", help="Write to this file instead of printing to stdout."
    ),
) -> None:
    """Export a goal's still-needed cards in TCGplayer Mass Entry format (one '<qty> <name>'
    line per card)."""
    db = SessionLocal()
    try:
        collection = get_or_create_default_collection(db)
        detail = goals_service.get_goal_need_list(db, goal_id, collection.id)
    finally:
        db.close()

    if detail is None:
        console.print(f"[red]No goal with id {goal_id}.[/red]")
        raise typer.Exit(code=1)

    text = goals_service.mass_entry_text(detail)
    if path:
        Path(path).write_text(text, encoding="utf-8")
        console.print(f"Wrote {path}")
    else:
        console.print(text, end="")


@sim_app.command("run")
def sim_run(
    goal_id: int,
    trials: int = 20_000,
    objective: str = "min_expected_cost",
    seed: int = 0,
) -> None:
    """Optimize a completion goal and print the ranked strategies."""
    try:
        parsed_objective = Objective(objective)
    except ValueError:
        console.print(
            f"[red]Unknown objective {objective!r}. Use one of: "
            f"{', '.join(o.value for o in Objective)}.[/red]"
        )
        raise typer.Exit(code=1) from None

    db = SessionLocal()
    try:
        try:
            result = run_search_and_cache(
                db, goal_id, parsed_objective, CostParams(), n_trials=trials, seed=seed
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        product_names = {
            p.id: p.name
            for p in db.execute(select(SealedProduct)).scalars().all()
        }
    finally:
        db.close()

    if result.unsimulatable:
        console.print("[yellow]Not simulatable:[/yellow]")
        for u in result.unsimulatable:
            console.print(f"  {u['name']} -- {u['reason']}")

    baseline = next((r for r in result.runs if not r.strategy_json), None)
    baseline_mean = baseline.results_json["mean"] if baseline else None

    console.print(f"Goal {goal_id} -- objective: {parsed_objective.value}")
    for run in result.runs:
        if run.strategy_json:
            label = ", ".join(
                f"{qty}x {product_names.get(int(pid), pid)}"
                for pid, qty in run.strategy_json.items()
            )
        else:
            label = "singles only"
        r = run.results_json
        delta = (
            f" ({r['mean'] - baseline_mean:+.2f} vs. singles)"
            if baseline_mean is not None and run.strategy_json
            else ""
        )
        console.print(
            f"  {label}: mean ${r['mean']:.2f}, p90 ${r['p90']:.2f}{delta}"
        )

    if result.uncovered_needed_price_sum:
        console.print(
            f"[yellow]${result.uncovered_needed_price_sum} of needed cards are outside this "
            "profile's rarity coverage and not reflected above -- add it by hand to any total "
            "you use.[/yellow]"
        )


@binder_app.command("create")
def binder_create(
    name: str = typer.Option(..., "--name", help="Human-readable binder name."),
    rows: int = typer.Option(3, "--rows", help="Pocket rows per page."),
    cols: int = typer.Option(3, "--cols", help="Pocket columns per page."),
    pages: int = typer.Option(20, "--pages", help="Number of pages."),
    top_loading: bool = typer.Option(
        False,
        "--top-loading",
        help="Top-loading pages. Gutter-spanning inserts are refused in these.",
    ),
    gutter_mm: int = typer.Option(6, "--gutter-mm", help="Gutter allowance between facing pages."),
) -> None:
    """Create an empty binder."""
    db = SessionLocal()
    try:
        binder = binder_service.create_binder(
            db,
            BinderData(
                name=name,
                rows=rows,
                cols=cols,
                pages=pages,
                is_side_loading=not top_loading,
                gutter_mm=gutter_mm,
            ),
        )
        loading = "side-loading" if binder.is_side_loading else "top-loading"
        console.print(
            f"Created binder {binder.id}: {binder.name!r} -- "
            f"{binder.rows}x{binder.cols}, {binder.pages} pages, {loading}"
        )
    finally:
        db.close()


@binder_app.command("list")
def binder_list() -> None:
    """List binders."""
    db = SessionLocal()
    try:
        binders = binder_service.list_binders(db)
    finally:
        db.close()
    if not binders:
        console.print("No binders yet -- create one with `bb binder create --name ...`.")
        return
    for b in binders:
        console.print(f"  {b.id}: {b.name!r} -- {b.rows}x{b.cols}, {b.pages} pages")


def _layout_source_set(db, set_code: str | None, goal_id: int | None) -> int | None:
    """Resolve the --set / --goal pair the layout commands share. Exactly one must be given;
    returns the set's row id, or None when laying out a goal."""
    if (set_code is None) == (goal_id is None):
        console.print("[red]Give exactly one of --set or --goal.[/red]")
        raise typer.Exit(code=1)
    if set_code is None:
        return None
    row = db.execute(select(SetModel).where(SetModel.ptcg_set_id == set_code)).scalar_one_or_none()
    if row is None:
        console.print(
            f"[red]No set with ptcg_set_id={set_code!r} -- "
            f"run `bb ingest cards --set {set_code}` first.[/red]"
        )
        raise typer.Exit(code=1)
    return row.id


@binder_app.command("auto-layout")
def binder_auto_layout(
    binder_id: int,
    set_id: str | None = typer.Option(None, "--set", help="ptcg_set_id, e.g. sv8."),
    goal_id: int | None = typer.Option(None, "--goal", help="Lay out exactly this goal's cards."),
    mode: str = typer.Option("set-order", "--mode", help="set-order | rarity-tiered"),
    master: bool = typer.Option(
        False, "--master", help="Place every printing, not just the canonical variant."
    ),
    skip_reverse_holos: bool = typer.Option(
        False, "--skip-reverse-holos", help="Leave reverse holos out of the layout."
    ),
    group_by_rarity: bool = typer.Option(
        False, "--group-by-rarity", help="Group by rarity within set order."
    ),
    start_subset_on_new_page: bool = typer.Option(
        False, "--subset-pages", help="Start each numbering subset (TG, GG, SV) on a fresh page."
    ),
    append: bool = typer.Option(
        False, "--append", help="Keep existing placements instead of replacing the layout."
    ),
) -> None:
    """Fill a binder from a set or a goal in card-number or rarity order."""
    try:
        parsed_mode = AutoLayoutMode(mode.replace("-", "_"))
    except ValueError:
        console.print(f"[red]Unknown mode {mode!r} -- use 'set-order' or 'rarity-tiered'.[/red]")
        raise typer.Exit(code=1) from None

    db = SessionLocal()
    try:
        set_row_id = _layout_source_set(db, set_id, goal_id)
        try:
            result = binder_service.apply_auto_layout(
                db,
                binder_id,
                set_row_id,
                goal_id=goal_id,
                mode=parsed_mode,
                canonical_only=not master,
                skip_reverse_holos=skip_reverse_holos,
                group_by_rarity=group_by_rarity,
                start_subset_on_new_page=start_subset_on_new_page,
                replace=not append,
            )
        except LookupError as exc:
            console.print(f"[red]{exc}.[/red]")
            raise typer.Exit(code=1) from None
        except LayoutError as exc:
            for error in exc.errors:
                console.print(f"[red]{error}[/red]")
            raise typer.Exit(code=1) from None
    finally:
        db.close()

    console.print(
        f"Placed {result.placed} cards across {result.pages_used} pages "
        f"({parsed_mode.value})."
    )
    if result.unplaced:
        console.print(
            f"[yellow]{result.unplaced} cards did not fit -- the binder needs more pages.[/yellow]"
        )
    if result.skipped_no_variant:
        console.print(
            f"[yellow]{result.skipped_no_variant} cards in this set have no printing row and "
            "could not be placed at all -- run `alembic upgrade head` or re-ingest the set's "
            f"cards (`bb ingest cards --set {set_id}`) to give them a placeholder.[/yellow]"
        )


@binder_app.command("show")
def binder_show(binder_id: int) -> None:
    """Print a binder page by page, flagging placements whose card is not in the collection."""
    db = SessionLocal()
    try:
        layout = binder_service.get_binder_layout(db, binder_id)
    finally:
        db.close()

    if layout is None:
        console.print(f"[red]No binder with id {binder_id}.[/red]")
        raise typer.Exit(code=1)

    loading = "side-loading" if layout.is_side_loading else "top-loading"
    console.print(
        f"Binder {layout.id}: {layout.name!r} -- {layout.rows}x{layout.cols}, "
        f"{layout.pages} pages, {loading}"
    )
    by_page: dict[int, list] = {}
    for p in layout.placements:
        by_page.setdefault(p.page_index, []).append(p)
    for page_index in sorted(by_page):
        console.print(f"  page {page_index}:")
        for p in sorted(by_page[page_index], key=lambda p: (p.row, p.col)):
            if p.kind == "card":
                label = f"{p.number} {p.card_name} ({p.variant})"
                owned = "" if p.is_owned else " [yellow]not owned[/yellow]"
            elif p.kind == "insert":
                label = f"insert #{p.insert_asset_id}"
                owned = " (spans gutter)" if p.spans_gutter else ""
            else:
                label = "empty"
                owned = ""
            console.print(f"    ({p.row},{p.col}) {label}{owned}")
    console.print(
        f"{len(layout.placements)} placements, "
        f"{layout.not_owned_count} of them not in the collection."
    )


@binder_app.command("export-json")
def binder_export_json(
    binder_id: int,
    path: str | None = typer.Option(
        None, "--path", help="Write to this file instead of printing to stdout."
    ),
) -> None:
    """Export a binder layout as portable JSON."""
    db = SessionLocal()
    try:
        payload = binder_service.export_layout_json(db, binder_id)
    finally:
        db.close()

    if payload is None:
        console.print(f"[red]No binder with id {binder_id}.[/red]")
        raise typer.Exit(code=1)

    text = json.dumps(payload, indent=2)
    if path:
        Path(path).write_text(text, encoding="utf-8")
        console.print(f"Wrote {path}")
    else:
        print(text)


@binder_app.command("import-json")
def binder_import_json(
    path: str,
    binder_id: int | None = typer.Option(
        None, "--binder", help="Replace this binder's layout instead of creating a new binder."
    ),
) -> None:
    """Import a layout JSON file exported by `bb binder export-json`."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        binder = binder_service.import_layout_json(db, payload, binder_id=binder_id)
    except LookupError:
        console.print(f"[red]No binder with id {binder_id}.[/red]")
        raise typer.Exit(code=1) from None
    except LayoutError as exc:
        for error in exc.errors:
            console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    finally:
        db.close()
    console.print(f"Imported into binder {binder.id}: {binder.name!r}")


@binder_app.command("add-insert")
def binder_add_insert(
    path: str,
    name: str = typer.Option("", "--name", help="Defaults to the file's stem."),
    width: int = typer.Option(1, "--width", help="Pockets wide."),
    height: int = typer.Option(1, "--height", help="Pockets tall."),
    source_note: str | None = typer.Option(None, "--source", help="Where the art came from."),
) -> None:
    """Store an insert image, refusing anything under 300 DPI at its target size."""
    file_path = Path(path)
    if not file_path.exists():
        console.print(f"[red]No such file: {path}[/red]")
        raise typer.Exit(code=1)
    db = SessionLocal()
    try:
        asset = save_insert(
            db,
            name=name,
            data=file_path.read_bytes(),
            filename=file_path.name,
            width_pockets=width,
            height_pockets=height,
            source_note=source_note,
        )
    except InsertError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    finally:
        db.close()
    console.print(
        f"Insert {asset.id}: {asset.name!r} -- {asset.width_pockets}x{asset.height_pockets} "
        f"pockets at {asset.dpi} DPI"
    )


@binder_app.command("list-inserts")
def binder_list_inserts() -> None:
    """List stored insert assets."""
    db = SessionLocal()
    try:
        assets = list_inserts(db)
    finally:
        db.close()
    if not assets:
        console.print("No inserts yet -- add one with `bb binder add-insert <path>`.")
        return
    for a in assets:
        console.print(
            f"{a.id:4d}  {a.name[:32]:32s}  {a.width_pockets}x{a.height_pockets}  {a.dpi} DPI"
        )


@binder_app.command("export-pdf")
def binder_export_pdf(
    binder_id: int,
    path: str = typer.Option("inserts.pdf", "--path", help="Where to write the PDF."),
    page_size: str = typer.Option("letter", "--page-size", help="letter | a4"),
) -> None:
    """Write the print-ready insert sheets.

    Print at 100% scale with "fit to page" off, or the whole point of the exact millimetre
    geometry is lost.
    """
    db = SessionLocal()
    try:
        out = export_binder_inserts_pdf(db, binder_id, path, page_size=page_size)
    except ExportError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    finally:
        db.close()
    console.print(f"Wrote {out}")
    console.print("[yellow]Print at 100% scale -- do not use 'fit to page'.[/yellow]")


@binder_app.command("export-png")
def binder_export_png(
    binder_id: int,
    spread: int = typer.Option(0, "--spread", help="Spread index; 0 is pages 1-2."),
    path: str | None = typer.Option(None, "--path", help="Defaults to spread-<n>.png."),
    dpi: int = typer.Option(150, "--dpi", help="Preview resolution."),
) -> None:
    """Render a spread preview at true proportions."""
    out_path = path or f"spread-{spread}.png"
    db = SessionLocal()
    try:
        out = export_binder_spread_png(db, binder_id, spread, out_path, dpi=dpi)
    except ExportError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    finally:
        db.close()
    console.print(f"Wrote {out}")


@binder_app.command("extract-colors")
def binder_extract_colors(
    set_code: str | None = typer.Option(None, "--set", help="ptcg_set_id, e.g. sv8. Omit for all."),
    limit: int | None = typer.Option(None, "--limit", help="Stop after this many cards."),
    refresh: bool = typer.Option(False, "--refresh", help="Recompute cards that already have one."),
) -> None:
    """Cache each card's dominant colour as CIELAB, for colour-themed Michi layouts.

    Downloads art once into the image cache, so a second run over the same set does no network
    work. Cards whose art will not download or decode are counted and skipped, never guessed.
    """
    db = SessionLocal()
    try:
        set_id = None
        if set_code:
            row = db.execute(
                select(SetModel).where(SetModel.ptcg_set_id == set_code)
            ).scalar_one_or_none()
            if row is None:
                console.print(f"[red]No set with ptcg_set_id {set_code!r}.[/red]")
                raise typer.Exit(code=1)
            set_id = row.id
        result = extract_colors(db, set_id=set_id, limit=limit, refresh=refresh)
    finally:
        db.close()
    console.print(
        f"{result.extracted} extracted, {result.already_cached} already cached, "
        f"{result.skipped_no_image} without usable art, {result.skipped_unreadable} unreadable "
        f"(of {result.considered} considered)"
    )
    if result.skipped_no_image:
        console.print(
            "[yellow]Cards without usable art keep a null colour and are grouped as 'misc' by "
            "colour clustering.[/yellow]"
        )


@binder_app.command("michi")
def binder_michi(
    binder_id: int,
    set_code: str | None = typer.Option(None, "--set", help="ptcg_set_id, e.g. sv8."),
    goal_id: int | None = typer.Option(None, "--goal", help="Lay out exactly this goal's cards."),
    key: str = typer.Option("species", "--key", help="species | artist | colour | evolution"),
    trials: int = typer.Option(24, "--trials", help="Best-of-N template/assignment trials."),
    seed: int = typer.Option(0, "--seed", help="Seeded, so a run is reproducible."),
    w_sym: float = typer.Option(0.30, "--w-symmetry"),
    w_col: float = typer.Option(0.25, "--w-colour"),
    w_hero: float = typer.Option(0.20, "--w-hero"),
    w_fill: float = typer.Option(0.15, "--w-fill"),
    w_orph: float = typer.Option(0.10, "--w-orphan"),
) -> None:
    """Lay a set out Michi-style: cluster, template, assign, score, best of N.

    Replaces the binder's whole layout. Run `bb binder extract-colors --set <id>` first if you
    want the colour terms to count for anything.
    """
    try:
        cluster_key = ClusterKey(key)
    except ValueError:
        valid = ", ".join(k.value for k in ClusterKey)
        console.print(f"[red]Unknown --key {key!r}. Use one of: {valid}.[/red]")
        raise typer.Exit(code=1) from None

    db = SessionLocal()
    try:
        set_row_id = _layout_source_set(db, set_code, goal_id)
        result = apply_michi_layout(
            db,
            binder_id,
            set_row_id,
            goal_id=goal_id,
            cluster_key=cluster_key,
            weights=ScoreWeights(w_sym, w_col, w_hero, w_fill, w_orph),
            trials=trials,
            seed=seed,
        )
    except LookupError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    except LayoutError as exc:
        for error in exc.errors:
            console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from None
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None
    finally:
        db.close()

    score = result.score
    console.print(
        f"{result.placed} placed across {result.groups} spreads "
        f"({result.unplaced} left over), best of {result.trials} trials"
    )
    console.print(f"score {score.total:.3f}")
    for name in ("symmetry", "colour", "hero", "fill"):
        value = getattr(score, name)
        shown = f"{value:.3f}" if value is not None else "not measured"
        console.print(f"  {name:9s} {shown}")
    console.print(f"  {'orphan':9s} {score.orphan:.3f} (penalty)")
    if "colour" in score.unmeasured:
        console.print(
            "[yellow]Colour coherence did not count: no card in this set has a dominant colour "
            "yet. Run `bb binder extract-colors --set " + set_code + "` first.[/yellow]"
        )


if __name__ == "__main__":
    app()
