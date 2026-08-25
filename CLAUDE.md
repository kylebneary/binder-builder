# CLAUDE.md — binder-builder

Context for Claude Code working in this repository. Read this first, then `docs/00-PRD.md`.

## What this project is

A local-first Pokémon TCG collection tool with three pillars:

1. **Tracker** — a Collectr-style collection manager (own/need, variants, conditions, portfolio value).
2. **Optimizer** — given a collecting goal and market prices, compute the cheapest expected path
   to completion across singles, sealed product, and hybrids, using Monte Carlo simulation over
   pack/box pull-rate models.
3. **Binder designer** — plan physical binder layouts, including Michi-method spreads with
   multi-pocket art inserts, and export print-ready insert PDFs.

## Stack (decided — do not re-litigate without asking)

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (typed ORM), Alembic, Pydantic v2.
- **Database:** SQLite by default (local-first, single file). All SQL must stay Postgres-compatible;
  no SQLite-only syntax. `DATABASE_URL` switches engines.
- **Stats:** NumPy for simulation. Vectorize Monte Carlo trials; do not loop in pure Python over
  100k trials.
- **Frontend:** React + TypeScript + Vite, TanStack Query, Tailwind. Keep it thin — business logic
  lives in the backend so it is testable and reusable from a CLI.
- **CLI:** Typer. Every optimizer/ingest capability must be reachable from the CLI without the UI.
- **Tests:** pytest. The simulation and cost math require unit tests with known-analytic cases.

The owner is most comfortable in Python and SQL. Prefer clear, boring Python over clever
abstractions. Keep the React surface small and conventional.

## Non-negotiable design rules

1. **Never hardcode prices or pull rates in code.** Prices come from ingested snapshots in the DB.
   Pull rates come from versioned YAML in `data/pull_rates/`, each with a source URL and a
   confidence rating. Every number a user sees must be traceable to a row or a file.
2. **Price identity is `(tcgplayer_product_id, sub_type_name)`, not the card.** A single card has
   separate market prices for Normal / Holofoil / Reverse Holofoil / 1st Edition variants. Modeling
   this wrong breaks the entire optimizer. See `docs/02-data-model.md`.
3. **Simulation is the source of truth, closed-form is a sanity check.** Box-level guarantees
   (e.g. "every box contains exactly N special illustration rares") break the independence
   assumption that closed-form coupon-collector math needs.
4. **Pull rates are estimates and must be displayed as such.** Always surface the confidence
   interval and the source. The Pokémon Company does not publish odds for English sets.
5. **Respect data sources.** tcgcsv.com publishes once daily at 20:00 UTC — cache and never poll
   faster. Do not scrape TCGplayer HTML. Do not commit bulk price data to git.

## Repo layout

```
backend/app/
  models/        SQLAlchemy ORM models (see docs/02-data-model.md)
  ingest/        Data source adapters (tcgcsv, pokemontcg.io) behind a common interface
  sim/           Pack/box simulation + completion cost optimizer
  binder/        Layout engine + print export
  api/           FastAPI routers
frontend/src/    React app
data/pull_rates/ Versioned per-set pull-rate profiles (YAML, human-edited, git-tracked)
docs/            Specs. Read before implementing the matching module.
scripts/         One-off maintenance scripts
```

## Working agreements

- Build in the order given in `docs/06-roadmap.md`. Phase 1 (tracker) must be usable before
  Phase 2 (optimizer) starts.
- When a spec in `docs/` is wrong or incomplete, update the doc in the same commit as the code.
- Add a new data source by writing an adapter in `backend/app/ingest/`, not by editing call sites.
- Money is `Numeric(10,2)` in the DB and `Decimal` in Python. Never float for currency. Floats are
  fine inside the simulator, which converts once at the boundary.
