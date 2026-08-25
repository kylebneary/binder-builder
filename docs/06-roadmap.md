# 06 — Roadmap & Task Backlog

Build in order. Each phase has an exit criterion; do not begin the next phase until it is met.
Phase 1 must be genuinely usable before Phase 2 starts — an optimizer with no collection data in it
is a toy.

---

## Branching

Never commit to `main`. One branch per slice, merged when its exit criteria are met:

| Branch | Covers |
|---|---|
| `feat/phase-1-data-ingest` | Phase 0 + tasks 1.1–1.4 |
| `feat/phase-1-set-mapping` | Tasks 1.5–1.6 |
| `feat/phase-1-tracker-ui` | Tasks 1.7–1.14 |
| `feat/phase-2-optimizer` | Phase 2 |
| `feat/phase-3-binder` | Phase 3 |

Phase 1 is three branches rather than one on purpose. Set mapping (1.5–1.6) is research-shaped
and will churn through many revisions; keeping it separate lets the schema and ingest work in
`feat/phase-1-data-ingest` merge to `main` early instead of waiting behind it.

---

## Phase 0 — Foundation ✅ done

**Branch:** `feat/phase-1-data-ingest`

**Exit:** `make dev` starts API and frontend; `pytest` passes; an empty DB migrates cleanly.

- [x] 0.1 Python project: `pyproject.toml`, ruff, mypy (non-strict initially), pytest.
- [x] 0.2 FastAPI app skeleton, `/health`, CORS for the Vite dev server.
- [x] 0.3 SQLAlchemy 2.0 base, session management, `DATABASE_URL` config.
- [x] 0.4 Alembic initialised with an empty baseline migration.
- [x] 0.5 Typer CLI entry point (`bb`), wired to the same settings.
- [x] 0.6 Vite + React + TS + Tailwind + TanStack Query scaffold; API client with generated types.
- [x] 0.7 `Makefile`: `dev`, `test`, `lint`, `migrate`, `ingest`.

## Phase 1 — Collection tracker ✅ done

**Branches:** `feat/phase-1-data-ingest` (1.1–1.4) · `feat/phase-1-set-mapping` (1.5–1.6) · `feat/phase-1-tracker-ui` (1.7–1.14)

**Exit:** the owner has entered a real collection for at least one full set and the portfolio value
matches a spot-check against TCGplayer within a few percent.

- [x] 1.1 Models + migration: `set`, `card`, `card_variant`.
- [x] 1.2 `PokemonTcgCardSource` adapter + `bb ingest cards --set sv8` / `--all`.
- [x] 1.3 Models + migration: `price_point`, and the `current_price` view.
- [x] 1.4 `TcgCsvPriceSource` adapter + `bb ingest prices [--date] [--backfill]`.
- [x] 1.5 **Set mapping**: build `data/set_map.yaml` (ptcg set → tcgcsv groupId) with a fuzzy-match
      helper script and a review report of unmatched sets. Hand-correct the residue.
- [x] 1.6 **Card→product mapping**: match cards to TCGplayer product IDs within a set; derive
      `card_variant` rows from the `subTypeName` values present. Report unmatched cards.
- [x] 1.7 Models + migration: `collection`, `collection_item`, `sealed_holding`.
- [x] 1.8 API: collection CRUD, set browse with owned/needed flags, portfolio summary.
- [x] 1.9 UI: set list, set detail grid with card images, owned/needed filter.
- [x] 1.10 UI: **fast bulk entry mode** — keyboard-driven walk through a set in number order,
      number keys set quantity, arrows navigate, `r` toggles reverse holo. Treat this as a
      first-class feature and time yourself using it; if entering 200 cards takes more than five
      minutes, it is not done.
- [x] 1.11 CSV import (Collectr, TCG Collector, Deckbox column mappings) with a dry-run diff.
- [x] 1.12 CSV export.
- [x] 1.13 Portfolio dashboard: value, cost basis, gain, value-over-time chart from price history.
- [x] 1.14 Sealed product catalogue: classify tcgcsv products as sealed, curate
      `data/sealed_map.yaml` for `product_type` and `packs_per_unit`.

**Real-data run (2026-08-25):** `bb ingest cards --all` / `build_set_map.py` / `bb sync setmap` /
`bb ingest prices` / `bb sync sealedmap` have now all been run for real against live pokemontcg.io
and tcgcsv data, not just fixtures. Results:

- **166 of 174 ptcg sets ingested.** The other 8 -- `smp`, `sv1`, `sv10`, `sve`, `swsh7`, `xy3`,
  `xy4`, `xyp` -- failed pokemontcg.io across four escalating retry passes (1s/3s/5s/20s backoff),
  a harder failure than this API's usual occasional-outage flakiness. `scripts/import_offline_cards.py`
  (+ `app/ingest/pokemontcg_offline.py`) exists as a manual fallback: hand-download the same JSON
  the CLI would fetch and import it from disk. At some point, worth looking into an alternative
  source for these 8 (e.g. the `PokemonTCG/pokemon-tcg-data` GitHub mirror) instead of continuing
  to retry the same flaky endpoint.
- `data/set_map.yaml`: 173 entries. Two set pairs -- `tk1a`/`tk1b` and `tk2a`/`tk2b` (the old EX
  Trainer Kit half-decks) -- can never be mapped: tcgcsv sells each pair as one combined product
  with overlapping card numbers between the two decks, and `Set.tcgplayer_group_id` is unique per
  set. Documented inline in the YAML.
- `data/sealed_map.yaml`: 517 of ~2,927 sealed products classified via name patterns unambiguous
  enough to apply mechanically (spot-checked for false positives first). The remaining ~2,400 are
  real hand-curation work -- pack counts for ETBs, checklane blisters, "Case" variants, etc. can't
  be inferred from the name alone, by design (see the file's own header comment).

Collection-entry spot-check against real TCGplayer prices (enter a real collection via the
bulk-entry UI, compare portfolio value) still hasn't happened -- that's the remaining piece before
Phase 1's exit criterion is *really* met, independent of the sealed-map curation above.

## Phase 2 — Completion optimizer

**Branch:** `feat/phase-2-optimizer`

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

**Branch:** `feat/phase-3-binder`

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

## Suggested next session for Claude Code

Phases 0 and 1 are done (see the outstanding real-data step noted under Phase 1, above -- do that
by hand or in the next session before trusting the numbers). Phase 2 starts fresh, on its own
branch: 2.1 (`goal`/`goal_item` models + migration + goal builder service) through 2.4 (pull-rate
YAML schema + loader) is a clean, self-contained slice that doesn't need the simulator yet. Stop
there -- 2.5 (authoring real pull-rate profiles) is the owner's research work, not Claude's, and
2.6+ (the actual simulator) needs those real profiles to test against.

## Where the hard parts are

1. ~~**1.5 / 1.6, the mapping problem.**~~ Done -- turned out to matter even more than expected:
   tcgcsv's own `cleanName` field mangles disambiguated card names, and its product names for
   sealed goods are genuinely unparseable (a real "Half Booster Box" SKU sits right next to
   "Booster Box" for the same set). Both are handled with review queues, not guesses.
2. **2.7 / 2.9, the vectorised simulator.** The naive implementation is easy and 100× too slow.
   Design for NumPy from the first line rather than optimising later.
3. **2.5, authoring pull-rate profiles.** This is research and judgement, not coding. Each set is
   an hour of reading community data and writing down what you believe and how confident you are.
