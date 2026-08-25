# 06 — Roadmap & Task Backlog

Build in order. Each phase has an exit criterion; do not begin the next phase until it is met.
Phase 1 must be genuinely usable before Phase 2 starts — an optimizer with no collection data in it
is a toy.

---

## Phase 0 — Foundation

**Exit:** `make dev` starts API and frontend; `pytest` passes; an empty DB migrates cleanly.

- [ ] 0.1 Python project: `pyproject.toml`, ruff, mypy (non-strict initially), pytest.
- [ ] 0.2 FastAPI app skeleton, `/health`, CORS for the Vite dev server.
- [ ] 0.3 SQLAlchemy 2.0 base, session management, `DATABASE_URL` config.
- [ ] 0.4 Alembic initialised with an empty baseline migration.
- [ ] 0.5 Typer CLI entry point (`bb`), wired to the same settings.
- [ ] 0.6 Vite + React + TS + Tailwind + TanStack Query scaffold; API client with generated types.
- [ ] 0.7 `Makefile`: `dev`, `test`, `lint`, `migrate`, `ingest`.

## Phase 1 — Collection tracker

**Exit:** the owner has entered a real collection for at least one full set and the portfolio value
matches a spot-check against TCGplayer within a few percent.

- [ ] 1.1 Models + migration: `set`, `card`, `card_variant`.
- [ ] 1.2 `PokemonTcgCardSource` adapter + `bb ingest cards --set sv8` / `--all`.
- [ ] 1.3 Models + migration: `price_point`, and the `current_price` view.
- [ ] 1.4 `TcgCsvPriceSource` adapter + `bb ingest prices [--date] [--backfill]`.
- [ ] 1.5 **Set mapping**: build `data/set_map.yaml` (ptcg set → tcgcsv groupId) with a fuzzy-match
      helper script and a review report of unmatched sets. Hand-correct the residue.
- [ ] 1.6 **Card→product mapping**: match cards to TCGplayer product IDs within a set; derive
      `card_variant` rows from the `subTypeName` values present. Report unmatched cards.
- [ ] 1.7 Models + migration: `collection`, `collection_item`, `sealed_holding`.
- [ ] 1.8 API: collection CRUD, set browse with owned/needed flags, portfolio summary.
- [ ] 1.9 UI: set list, set detail grid with card images, owned/needed filter.
- [ ] 1.10 UI: **fast bulk entry mode** — keyboard-driven walk through a set in number order,
      number keys set quantity, arrows navigate, `r` toggles reverse holo. Treat this as a
      first-class feature and time yourself using it; if entering 200 cards takes more than five
      minutes, it is not done.
- [ ] 1.11 CSV import (Collectr, TCG Collector, Deckbox column mappings) with a dry-run diff.
- [ ] 1.12 CSV export.
- [ ] 1.13 Portfolio dashboard: value, cost basis, gain, value-over-time chart from price history.
- [ ] 1.14 Sealed product catalogue: classify tcgcsv products as sealed, curate
      `data/sealed_map.yaml` for `product_type` and `packs_per_unit`.

## Phase 2 — Completion optimizer

**Exit:** for a real set and a real collection, the tool produces a ranked strategy list with a
cost distribution and a sensitivity chart, and the analytic-agreement test passes.

- [ ] 2.1 Models + migration: `goal`, `goal_item`; goal builder service (set / master set / filter).
- [ ] 2.2 API + UI: create a goal, see the need list and its plain singles cost.
- [ ] 2.3 Shipping and liquidation cost models with configurable parameters.
- [ ] 2.4 Pull-rate YAML schema, Pydantic validators, `bb sync pullrates` loader.
- [ ] 2.5 Author profiles for 3–5 sets the owner actually collects, with sources and confidence.
- [ ] 2.6 `sim/analytic.py` — closed-form expected remaining cost.
- [ ] 2.7 `sim/montecarlo.py` — vectorised NumPy engine, box constraints, seeded RNG.
- [ ] 2.8 Test suite from `docs/04-optimizer-spec.md` (all six categories).
- [ ] 2.9 Performance pass to the 100k-trials-in-2s target.
- [ ] 2.10 Strategy search: grid for ≤2 product types, greedy for more.
- [ ] 2.11 Objectives: expected cost, p90 cost, budget-constrained completion.
- [ ] 2.12 `simulation_run` persistence and cache.
- [ ] 2.13 UI: results view — strategy ranking, cost histogram, singles baseline delta,
      assumptions panel with inline editing.
- [ ] 2.14 Sensitivity/tornado analysis and the "recommendation is not robust" warning.
- [ ] 2.15 Shopping list export in TCGplayer Mass Entry format.

## Phase 3 — Binder designer

**Exit:** the owner has designed a real binder, printed inserts from the PDF, and they fit the
pockets.

- [ ] 3.1 Models + migration: `binder`, `binder_page`, `binder_placement`, `insert_asset`.
- [ ] 3.2 Layout service with overlap and gutter invariants.
- [ ] 3.3 API + UI: create a binder, drag-and-drop pocket grid, spread preview.
- [ ] 3.4 Insert upload, DPI validation, multi-pocket span placement.
- [ ] 3.5 Auto-layout: set order and rarity-tiered.
- [ ] 3.6 Dominant-colour extraction (CIELAB, cached on `card`).
- [ ] 3.7 Template library (`data/binder_templates/`, ~8 hand-designed 3×3 spreads).
- [ ] 3.8 Michi auto-layout with the scoring function from `docs/05-binder-spec.md`.
- [ ] 3.9 Print export: insert PDF with bleed and crop marks, sheet packing.
- [ ] 3.10 Spread preview PNG export.
- [ ] 3.11 "Not owned" badges and count.
- [ ] 3.12 Undo/redo.

## Phase 4 — Polish (only if 1–3 are being used)

- [ ] 4.1 eBay sold-comp adapter for better resale pricing (likely paid).
- [ ] 4.2 Price alerts on need-list cards.
- [ ] 4.3 Multi-goal portfolio view.
- [ ] 4.4 Japanese set support (TCGdex; different pack structures and published box odds).
- [ ] 4.5 Community pull-rate contribution: log your own pack openings and update profile posteriors.

---

## Suggested first session for Claude Code

Phase 0 in full, then 1.1 → 1.4. That gets real card data and real prices into a real database,
which makes everything after it concrete. Stop there and let the owner inspect the data before
building UI on top of it.

## Where the hard parts are

Three things will take longer than they look, and none of them is the UI:

1. **1.5 / 1.6, the mapping problem.** Joining pokemontcg.io cards to TCGplayer product IDs has no
   shared key and the long tail of promos, subsets, and reprints is genuinely messy. Budget real
   time, build the review queue, and do not let unmatched cards fail silently.
2. **2.7 / 2.9, the vectorised simulator.** The naive implementation is easy and 100× too slow.
   Design for NumPy from the first line rather than optimising later.
3. **2.5, authoring pull-rate profiles.** This is research and judgement, not coding. Each set is
   an hour of reading community data and writing down what you believe and how confident you are.
