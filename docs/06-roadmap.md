# 06 — Roadmap & Task Backlog

Build in order. Each phase has an exit criterion; do not begin the next phase until it is met.
Phase 1 must be genuinely usable before Phase 2 starts — an optimizer with no collection data in it
is a toy.

For missing *data* specifically (sets not yet ingested, pull-rate profiles not yet authored,
price/variant gaps) see `docs/07-data-backlog.md` — it's the checklist to work from rather than
re-discovering the same gaps each session.

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

- [x] 2.1 Models + migration: `goal`, `goal_item`; goal builder service (set / master set / filter).
- [x] 2.2 API + UI: create a goal, see the need list and its plain singles cost.
- [x] 2.3 Shipping and liquidation cost models with configurable parameters.
- [x] 2.4 Pull-rate YAML schema, Pydantic validators, `bb sync pullrates` loader.
- [x] 2.5 Author profiles for 3–5 sets the owner actually collects, with sources and confidence.
- [x] 2.6 `sim/analytic.py` — closed-form expected remaining cost.
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

**2.1–2.4 shipped (2026-08-25):** `Goal`/`GoalItem`/`PullRateProfile`/`PackSlot`/`SlotOutcome`/
`BoxConstraint` models and their baseline migration already existed from initial scaffolding, so
this slice built the service/API/CLI layer around them: `services/goals.py` (goal builder for
`set`/`master_set`/`filter` types, materialising `goal_item` as a wholesale delete-and-reinsert,
plus the need-list view), `services/costs.py` (Decimal seller-consolidation shipping + liquidation
math per `docs/04-optimizer-spec.md`), `ingest/pullrates.py` (Pydantic structural validation +
DB-dependent rarity-existence check), and `bb goal create` / `bb goal need-list` / `bb sync
pullrates` CLI commands. API at `/api/v1/goals`; UI at `/goals` and `/goals/:goalId` (set/
master_set creation only -- a filter-builder UI is deferred, see `services/goals.py`'s docstring).
Verified against the real ingested DB: `sv8` master-set goal → 411 needed cards, $1338.92 total
(35 consolidated orders); plain `set` goal → 249 cards, $1177.47. Both confirmed rendering
correctly in a real browser (Playwright), not just via the API. `bb sync pullrates` correctly
skips `_TEMPLATE.yaml`/`EXAMPLE-*.yaml` and reports nothing to sync, since no real profile had
been authored yet at that point -- see 2.5, below.

**2.5 shipped (2026-08-25):** authored 10 real profiles, all sourced and confidence-rated,
covering every set from the owner's actual collection CSV that (a) is already ingested and (b)
doesn't hit the Trainer-Gallery/Galarian-Gallery schema gap described below.

*`confidence: medium`* -- `sv2` (Paldea Evolved), `sv3pt5` (151), `sv7` (Stellar Crown), `sv8`
(Surging Sparks, superseding the old illustrative `EXAMPLE-sv8.yaml`, now deleted). Hit-rarity
probabilities come from TCGplayer Authentication Center's per-set pull-rate articles (1,500-8,000+
real packs each, 95% CI) -- their reported card counts per rarity matched this project's ingested
card data exactly for all four sets, strong corroboration. Two things are explicitly *not* sourced
and called out in each YAML's own notes: the 55/35/10 split of each reverse-holo slot's non-hit
filler across Common/Uncommon/Rare (the project's original placeholder assumption -- TCGplayer's
articles only report hit rates), and box-level collation guarantees (none declared -- packs are
modeled as independent, since TCGplayer's methodology samples packs, not boxes). That gap is why
these are `medium`, not `high`.

*`confidence: low`* -- `swsh1` (Sword & Shield), `swsh2` (Rebel Clash), `swsh3` (Darkness Ablaze),
`swsh5` (Battle Styles), `swsh6` (Chilling Reign), `swsh8` (Fusion Strike). No TCGplayer
Authentication Center article exists for these at SV-era rigor, so per the owner's explicit
call ("even estimates will have to do") these use thepricedex.com, a third-party aggregator that
itself cites "community research" (a disclosed 5,000-pack Reddit sample for Chilling Reign,
1,405 for Battle Styles, undisclosed for the rest) rather than a verified first-party study.
Each YAML's header says so plainly and is explicit that "the whole profile" is the least-trusted
figure, not just one field. The reverse-holo-slot split for all six is taken from thepricedex's
Darkness Ablaze page (the only one of the six with reverse-card odds) and reused as a same-era
approximation for the other five, not re-derived per set. All ten profiles pass `bb sync
pullrates` against the live DB and are idempotent on resync; the full test suite stays green.

Three things were found and deliberately *not* forced into a profile, rather than papered over:
- **Crown Zenith** (`swsh12pt5`) has real 1,900-pack TCGplayer data available but hits a genuine
  schema gap: its hit slot draws from the separate `swsh12pt5gg` Galarian Gallery set, which
  `pull_rate_profile`'s single-`set_id` design can't represent -- see the new note in
  `docs/02-data-model.md`'s Pull-rate model section. Same blocker applies to every other
  SWSH-era Trainer Gallery set (Brilliant Stars, Astral Radiance, Lost Origin, Silver Tempest)
  and to Shining Fates' Shiny Vault subset -- a schema change, not more research, is the
  prerequisite.
- **Pokémon GO** (`pgo`) -- despite being the owner's single most-collected set by card count --
  has no TCGplayer article and nothing on thepricedex either; no source clearing even the relaxed
  "low confidence, real numbers" bar was found. It's also a special product (sold only as
  standalone packs, no booster box), which would need its own box-less cost-model handling later
  regardless.
- **Vivid Voltage** (`swsh4`) was skipped: it introduced the one-off "Amazing Rare" rarity, which
  none of the sources found (TCGplayer or thepricedex) account for, and fabricating that
  probability from nothing would misrepresent the set's actual card pool.

Pre-existing data-quality finding, unrelated to pull rates but discovered while cross-checking
these: every SWSH-era set checked (`swsh1`/`2`/`3`/`5`/`6`/`8`, likely all of them) has `card`
rows for Rare Ultra/Rare Rainbow/Rare Secret but **zero** priced `card_variant` rows for those
same rarities -- a real ingest gap (the cards exist, nothing prices them), noted here rather than
silently worked around. It doesn't block pull-rate sync (validation only checks `card.rarity`),
but it means need-list cost for those specific cards will show as unpriced until it's fixed.

**2.6 shipped (2026-08-25):** `sim/analytic.py` implements `per_pack_probability` (P(a given pool
card appears in a given pack), combining every contributing slot outcome multiplicatively so a
card referenced by more than one slot -- e.g. a dedicated "rare" slot and a hit slot's normal-Rare
filler outcome, both present in the spec's own example YAML -- is handled correctly) and
`expected_remaining_singles_cost` (`Σ price · (1-p)^k` over needed cards). Along the way, a real
gap in `sim/types.py`'s `CardPool` was found and fixed: it had no way to distinguish variant
(normal/holofoil/reverse_holofoil/...) within a rarity, so a reverse-holo slot outcome couldn't be
matched to only reverse-holo pool entries -- exactly the failure mode
`docs/04-optimizer-spec.md` warns "master-set goals will never complete" if gotten wrong. Added a
`variant_index`/`variants` field pair (mirrors the existing `rarity_index`/`rarities` pattern) and
an `indices_for(rarity, variant)` helper that returns empty rather than raising when a
(rarity, variant) combo has no pool entries -- deliberately tolerant, since the SWSH Rare
Ultra/Rainbow/Secret zero-variant gap (above) means a real profile can reference a combo that
doesn't exist in the priced pool yet. 8 new unit tests in `backend/tests/test_sim_analytic.py`
cover: uniform single-slot probability, multi-slot combination, variant matching, the
missing-variant-is-zero-not-error case, an exact hand-calculated value, the `k=0` degenerate case,
excluding not-needed cards, and monotonicity in `k`. Full suite: 113 passing.

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
by hand or in the next session before trusting the numbers). Phase 2's 2.1-2.6 are all done (see
the notes under Phase 2, above): goal creation, the need list, its plain singles cost, ten real
pull-rate profiles (4 `medium`-confidence TCGplayer-sourced SV-era sets, 6 `low`-confidence
thepricedex-sourced SWSH-era sets), and the closed-form `sim/analytic.py` oracle all work and are
unit-tested (113 passing). Next is 2.7: `sim/montecarlo.py`, the vectorised NumPy engine -- it can
reuse `sim/analytic.py`'s new `CardPool.variant_index`/`indices_for` plumbing directly for
uniform-within-rarity draws. It doesn't strictly need `box_constraints` to get started (`draw_box`
without any `guarantees` should degenerate to the same independent-draw model analytic.py uses,
which is exactly what 2.8's "analytic agreement" test will check), but exercising the box-collation
code path *properly* needs a profile that actually has a `box_constraint` -- none of the ten
authored so far do, since no sourced box-guarantee data was found for any of them. Worth either
researching that for one set, or accepting box_constraints coverage as synthetic-data-only (a
hand-built test fixture) until a source turns up.

Separately, if picking up pull-rate authoring again: the Trainer-Gallery/Galarian-Gallery schema
gap (see the Phase 2 note above and `docs/02-data-model.md`'s Pull-rate model section) blocks
Crown Zenith, Brilliant Stars, Astral Radiance, Lost Origin, Silver Tempest, and Shining Fates --
real source data exists for several of these, the schema is what's missing. Pokémon GO and Vivid
Voltage are blocked on not having found adequate source data, not on schema.

## Where the hard parts are

1. ~~**1.5 / 1.6, the mapping problem.**~~ Done -- turned out to matter even more than expected:
   tcgcsv's own `cleanName` field mangles disambiguated card names, and its product names for
   sealed goods are genuinely unparseable (a real "Half Booster Box" SKU sits right next to
   "Booster Box" for the same set). Both are handled with review queues, not guesses.
2. **2.7 / 2.9, the vectorised simulator.** The naive implementation is easy and 100× too slow.
   Design for NumPy from the first line rather than optimising later.
3. **2.5, authoring pull-rate profiles.** This is research and judgement, not coding. Each set is
   an hour of reading community data and writing down what you believe and how confident you are.
