# binder-builder

A local-first Pokémon TCG toolkit: track what you own, compute the cheapest way to finish a set,
and design the binder you'll put it in.

Three pillars:

1. **Tracker** — Collectr-style collection management, per printing variant, with daily price
   history and portfolio value.
2. **Optimizer** — Monte Carlo simulation over pack and box pull rates to answer "singles, sealed,
   or both?" with a cost *distribution* rather than a point estimate, net of what duplicates
   resell for.
3. **Binder designer** — plan layouts including Michi-method spreads with multi-pocket art
   inserts, and export print-ready insert PDFs.

## Status

Phase 0 scaffold. Nothing is implemented yet — the specs are written and the skeleton compiles.
Start at `docs/06-roadmap.md`.

## Documentation

| Doc | What it covers |
|---|---|
| `CLAUDE.md` | Context and working rules for Claude Code. **Read first.** |
| `docs/00-PRD.md` | What this is, who it's for, what it will not do |
| `docs/01-architecture.md` | Layers, adapters, jobs, testing strategy |
| `docs/02-data-model.md` | Full schema and the one rule that matters |
| `docs/03-data-sources.md` | Verified APIs, schemas, and the pull-rate problem |
| `docs/04-optimizer-spec.md` | The statistics. Read before touching `sim/`. |
| `docs/05-binder-spec.md` | Michi method, layout model, print export |
| `docs/06-roadmap.md` | Phased backlog with exit criteria |

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 · Alembic · SQLite (Postgres-compatible) · NumPy · Typer
React 18 · TypeScript · Vite · TanStack Query · Tailwind

## Quick start

```bash
cp .env.example .env
make install
make migrate
make api            # http://localhost:8000/health
make web            # http://localhost:5173
```

Then, in order:

```bash
bb ingest cards --set sv8       # card metadata from pokemontcg.io
bb ingest prices                # daily prices from tcgcsv.com
bb sync pullrates               # load data/pull_rates/*.yaml
```

## Data sources

Card metadata from [pokemontcg.io](https://docs.pokemontcg.io/); prices — including sealed
products — from [tcgcsv.com](https://tcgcsv.com/), which mirrors TCGplayer daily at ~20:00 UTC.
Both are free. Pull rates are **not** fetched: no authoritative source exists for English sets, so
they live as versioned YAML in `data/pull_rates/` with sources and confidence ratings attached.

## The honest caveat

Pull rates for English Pokémon product are unpublished. Every figure this tool uses is a community
estimate of unknown sample size. The optimizer therefore reports percentiles and runs sensitivity
analysis by default, and will tell you when a recommendation is not robust to plausible changes in
those estimates. Treat its output as a well-reasoned argument, not an oracle.
