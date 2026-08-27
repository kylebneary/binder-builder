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

- **174 of 174 ptcg sets ingested.** 166 came from the live API directly; the other 8 -- `smp`,
  `sv1`, `sv10`, `sve`, `swsh7`, `xy3`, `xy4`, `xyp` -- failed pokemontcg.io across four escalating
  retry passes (1s/3s/5s/20s backoff), a harder failure than this API's usual occasional-outage
  flakiness. Resolved 2026-08-25 via a new `app/ingest/pokemontcg_github.py` adapter
  (`PokemonTcgGithubMirrorSource`) that reads the same card/set JSON from the
  `PokemonTCG/pokemon-tcg-data` GitHub mirror instead (`bb ingest cards --source github-mirror
  --set <id>`) -- all 8 fetched cleanly on the first attempt. `data/set_map.yaml` already had
  tcgcsv group mappings for all 8; `bb sync setmap` + `bb ingest prices` linked them and pulled
  real prices. See `docs/03-data-sources.md`'s "Fallback: the pokemontcg-data GitHub mirror" and
  `docs/07-data-backlog.md` §1 for detail. `scripts/import_offline_cards.py` (+
  `app/ingest/pokemontcg_offline.py`) still exists as a last-resort manual fallback if the mirror
  is ever down too.
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
- [x] 2.7 `sim/montecarlo.py` — vectorised NumPy engine, box constraints, seeded RNG.
- [x] 2.8 Test suite from `docs/04-optimizer-spec.md` (all six categories).
- [x] 2.9 Performance pass to the 100k-trials-in-2s target.
- [x] 2.10 Strategy search: grid for ≤2 product types, greedy for more.
- [x] 2.11 Objectives: expected cost, p90 cost, budget-constrained completion.
- [x] 2.12 `simulation_run` persistence and cache.
- [x] 2.13 UI: results view — strategy ranking, cost histogram, singles baseline delta,
      assumptions panel with inline editing.
- [x] 2.14 Sensitivity/tornado analysis and the "recommendation is not robust" warning.
- [x] 2.15 Shopping list export in TCGplayer Mass Entry format.

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

**2.5 shipped (2026-08-25):** authored 10 real profiles initially (`swsh4` and `pgo` followed
later the same day -- see below), all sourced and confidence-rated, covering every set from the
owner's actual collection CSV that (a) is already ingested and (b) doesn't hit the
Trainer-Gallery/Galarian-Gallery schema gap described below.

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
approximation for the other five (and, later, for `swsh4` too). All profiles pass `bb sync
pullrates` against the live DB and are idempotent on resync; the full test suite stays green.

Two things were found and deliberately *not* forced into a profile, rather than papered over:
- **Crown Zenith** (`swsh12pt5`) has real 1,900-pack TCGplayer data available but hits a genuine
  schema gap: its hit slot draws from the separate `swsh12pt5gg` Galarian Gallery set, which
  `pull_rate_profile`'s single-`set_id` design can't represent -- see the new note in
  `docs/02-data-model.md`'s Pull-rate model section. Same blocker applies to every other
  SWSH-era Trainer Gallery set (Brilliant Stars, Astral Radiance, Lost Origin, Silver Tempest)
  and to Shining Fates' Shiny Vault subset -- a schema change, not more research, is the
  prerequisite.
- **Vivid Voltage** (`swsh4`) was initially skipped: it introduced the one-off "Amazing Rare"
  rarity, which the sources checked at the time (TCGplayer, thepricedex) appeared not to account
  for. **Revisited and authored 2026-08-25** (`docs/07-data-backlog.md` 2b): a second look at
  thepricedex.com found a Vivid Voltage page after all, with Amazing Rare odds included -- the
  earlier pass had simply missed it. See `data/pull_rates/swsh4.yaml`.

**Pokémon GO** (`pgo`) was also initially skipped -- despite being the owner's single
most-collected set by card count, no TCGplayer article and (it seemed) nothing on thepricedex
either. **Revisited and authored 2026-08-25**, same as `swsh4`: thepricedex does have a `pgo`
page after all, covering every rarity including the set-specific "Radiant Rare", and -- unlike
every SWSH-era profile above -- it reports its own reverse-holo odds directly rather than needing
a borrowed split. See `data/pull_rates/pgo.yaml`. It remains a special case in one other way,
unrelated to pull rates: sold only as standalone packs with no booster-box SKU, so it'll still
need box-less sealed-cost handling in `docs/04-optimizer-spec.md`'s cost math before a goal for
this set can price a sealed strategy.

12 profiles total as of 2026-08-25 (10 initial + `swsh4` + `pgo`).

Pre-existing data-quality finding, unrelated to pull rates but discovered while cross-checking
these: every SWSH-era set checked (`swsh1`/`2`/`3`/`4`/`5`/`6`/`8`, likely all of them) plus `pgo`
has `card` rows for Rare Ultra/Rare Rainbow/Rare Secret but **zero** priced `card_variant` rows
for those same rarities -- a real ingest gap (the cards exist, nothing prices them), noted here
rather than silently worked around. It doesn't block pull-rate sync (validation only checks
`card.rarity`), but it means need-list cost for those specific cards will show as unpriced until
it's fixed. **Root-caused and mostly fixed 2026-08-25** -- see `docs/07-data-backlog.md` §3: it
was `app/ingest/mapping.py` failing to recognize tcgcsv's special-treatment naming suffixes
("Full Art", "Rainbow Rare", etc.), not a missing source; coverage across the 8 sets went from
0 of 302 to 291 of 302 after adding `strip_known_treatment_suffix()` and re-ingesting.

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

**2.7-2.9 shipped (2026-08-25):** `sim/montecarlo.py` implements `draw_boxes`, `singles_cost`,
`liquidation_value`, and `simulate`, plus a new `services/simulate.py` (the DB <-> sim boundary --
`build_card_pool`, `resolve_pull_rate_profile`, `build_box_spec`, `sealed_unit_price`).

Two design decisions worth flagging:
- **Scatter-add uses `np.bincount`, not `np.add.at`.** Every card pulled across every
  slot/repeat/guarantee is appended as a flat `trial*n_pool + card` index; one `bincount` call at
  the end builds the `(n_trials, n_pool)` count matrix. This is what makes the 100k-trials/
  36-pack-box/~200-card performance contract (2.9) achievable without a rewrite -- measured
  1.5-1.85s across repeated runs on this dev machine, comfortably under the 2s budget (benchmark
  test in `test_sim_montecarlo.py`, tagged `@pytest.mark.slow` and skipped by default --
  `pyproject.toml` now has `addopts = "-m 'not slow'"`; run explicitly with `pytest -m slow`).
- **Box guarantees are additive, not renormalising.** `_draw_box_guarantees` samples without
  replacement from a guaranteed rarity's pool per `(trial, box)` instance (vectorised via
  argsort-of-random-keys, no per-instance Python loop) and adds the result on top of the ordinary
  independent slot draws, rather than removing/renormalising the slot outcome that would have
  produced the same rarity. Documented, not silent: in the rare case a guaranteed rarity is also
  independently hit by its normal slot, a box can end up with one more copy than a strictly
  collated model would produce. Irrelevant today since zero real profiles have `box_constraints`
  yet (see `docs/07-data-backlog.md`); the spec's own "every box contains exactly N" test bar is
  verified against a synthetic fixture where the guaranteed rarity is isolated from every regular
  slot, so the test is exact despite the approximation.

A real gap was found and closed in `services/simulate.py`: `sealed_product.pack_config_id` (FK to
`pull_rate_profile`) exists in the schema but nothing has ever set it. `resolve_pull_rate_profile`
honors it if explicitly set, else falls back to the target set's `is_default` profile -- no new
sync/data-entry work needed, and every real lookup today uses the fallback path. A second,
smaller gap: a sealed product's own current price is keyed `(tcgplayer_product_id,
sub_type_name="Normal")` in `current_price` (confirmed in `app/ingest/tcgcsv.py` -- tcgcsv's
`subTypeName` is null for sealed goods and the adapter defaults it to `"Normal"`); `sealed_unit_price`
uses that fixed key rather than guessing.

A correctness edge case was found and handled rather than deferred: a goal can include needed
cards whose rarity has zero coverage in a profile's slot outcomes/box constraints at all (a promo
rarity, or the unmodeled "Foil Energy" slot some SV-era YAMLs already note) -- no sealed strategy
can ever produce them, sealed or not. `build_card_pool` now returns
`uncovered_needed_price_sum` (a plain Decimal) alongside the pool so callers can add it as a flat
NetCost floor on every strategy, keeping totals reconciled with `services/goals.get_goal_need_list`
instead of silently undercounting. `sim/types.py`'s `BoxSpec` also gained a `unit_price: float`
field (mirroring how `CardPool` gained `variant_index` in 2.6) since `simulate()` needs a sealed
unit's price to compute `SealedCost` and that's not derivable from anything else in `BoxSpec`.

17 new tests: `test_sim_montecarlo.py` covers all six categories from
`docs/04-optimizer-spec.md`'s "Testing" section (analytic agreement within 3 SE, coupon-collector
sanity via a from-scratch sequential-completion simulation, degenerate cases, byte-identical
determinism, exact box-guarantee counts, monotonicity in `k`) plus the performance benchmark;
`test_service_simulate.py` covers pool scoping, the uncovered-needed accounting,
owned-card exclusion, profile resolution (default vs. explicit override), and box-spec building
(including missing `packs_per_unit` and `box_constraint` mapping). Full suite: 130 passing (1
slow test deselected by default).

**2.10-2.12 shipped (2026-08-25):** `sim/optimizer.py` implements `search` (ranked
`(Strategy, SimResult)` pairs, always including the singles-only baseline; exhaustive grid for
<=2 sealed products, greedy marginal analysis + a +-1 local-search polish for 3+) and
`sensitivity` (tornado analysis: top-3 needed chase-rarity pull rates at +/-50%,
`liquidation_rate` 0.5-0.85, sealed unit price +/-20%; `robust: bool` flags whether any
perturbation flips which of the strategy/singles-baseline is cheaper). Two precision/scope
decisions worth flagging:
- **Two-phase precision in `search`.** Candidate generation and initial ranking run at a
  lower `n_trials` (capped at 5,000) for speed; the top 3 candidates plus the baseline are
  re-simulated at the caller's full `n_trials` before the final ranking is returned. A real
  trade-off (coarse-phase noise could misorder two very close candidates before refinement
  corrects it), documented in the function's docstring rather than silent.
- **Price-basis (low/market/high) sensitivity is deferred to Milestone D.** `build_card_pool`
  gained a `price_field` parameter so the service layer can build alternate pools for this later;
  `sim/optimizer.py` can't call `get_current_prices` itself (DB-oblivious per
  `docs/01-architecture.md`), and wiring that orchestration in now would anticipate UI work not
  yet built. The other three sensitivity factors ship now since they're self-contained within
  `sim/`.

New `services/simulation_runs.py` is the caching/persistence layer: `compute_cache_key` hashes
`(goal, strategy, params, n_trials, seed, price_date, profile_version)` per the spec's "cache
aggressively" note -- one `simulation_run` row per evaluated strategy point, so a repeated search
over an already-cached point is free. `price_date` uses the global max `price_point.observed_on`
(the daily price job ingests everything in one batch, so this is a fair proxy) rather than
per-product dates. `run_search_and_cache` resolves every sealed product for the goal's set that
shares its profile with the set's `is_default` profile into a `BoxSpec`, reporting (never
silently dropping) any that aren't simulatable and why.

New `POST /api/v1/goals/{goal_id}/simulate` (body: `objective`, `n_trials`, `seed`,
`sealed_product_ids`, optional `CostParams` overrides) and `bb sim run <goal_id>` both wrap
`run_search_and_cache`. Verified end-to-end against the real ingested DB: `bb sim run 1` (the
existing `sv8` master-set goal) against the already-curated real `packs_per_unit` sealed products
for that set (single-pack products; the Booster Box itself is still uncurated in
`data/sealed_map.yaml`, per the Phase 1 backlog) -- singles-only baseline reported **$1338.92
mean**, exactly matching the plain need-list total from the 2.1-2.4 shipped note above, confirming
the `uncovered_needed_price_sum` reconciliation design holds in practice. Every real sealed
product for `sv8` came back slightly more expensive than singles-only, consistent with the spec's
"Expected finding" that sealed usually loses.

13 new tests: `test_sim_optimizer.py` (baseline inclusion, grid picks the cheaper synthetic
strategy, greedy activates at 3+ products, results sorted by objective, sensitivity reports
`robust`/factors), `test_service_simulation_runs.py` (persistence, cache hit/miss on changed
params, unsimulatable-product reporting), plus an API smoke test in the new
`test_api_simulate.py`. Full suite: 147 passing (1 slow deselected).

**2.13 shipped (2026-08-25):** `GET /sets/{ptcg_set_id}/sealed-products` (new
`services/sets.list_sealed_products`) lists every sealed product for a set with current price and
a `has_pull_rate_profile` flag, so the UI can grey out products that would otherwise just come
back in `run_search_and_cache`'s `unsimulatable` list. `frontend/src/pages/GoalSimulatePage.tsx`
(route `/goals/:goalId/simulate`, linked from a new "Run optimizer" button on
`GoalDetailPage.tsx`) is the results view: a sealed-product picker, objective selector and
editable `liquidation_rate`/`resale_floor`, a ranked-strategies table (mean/p90/completion%/delta
vs. singles, best strategy highlighted), and a cost histogram (`recharts` `BarChart`, reusing the
same lazy-chunk-splitting pattern `PortfolioPage.tsx` already uses since `recharts` is a large
dependency). `SimResultOut` gained `histogram_counts`/`histogram_edges` fields (present in
`results_json` since 2.10-2.12 but not previously exposed over the API) to feed the chart.

Verified in a real headless-Chromium browser (Playwright) against the real ingested DB, not just
via the API: navigated to the `sv8` master-set goal, opened the simulate page, ran the optimizer
with defaults, and confirmed the picker correctly greys out the ~15 uncurated sealed products
(Booster Box included -- still unmapped in `data/sealed_map.yaml`), the ranked table reproduces
the same `$1338.92` singles-only baseline as the CLI verification above, and the histogram renders
(a single sharp spike for the singles-only strategy, which is the *correct* shape -- singles-only
has no pack-pull randomness at all, all of the model's variance comes from opening packs). Zero
console errors. `npm run build` (tsc typecheck + vite build) clean.

**2.14/2.15 shipped (2026-08-26).** `sim/optimizer.sensitivity()`
gained a `price_basis_pools` parameter -- the low/market/high perturbation deferred in the 2.10-2.12
note above -- fed by `build_card_pool`'s existing `price_field` parameter via a new
`services/simulation_runs.run_sensitivity()` (not persisted as a `simulation_run` row; it's a
multi-simulation derived analysis, not a single reproducible run, so it would need its own
cache-key shape to be worth caching). New `POST /goals/{id}/sensitivity` and `bb goal
export-mass-entry <goal_id> [--path FILE]` (implemented against a new `services/goals.
mass_entry_text()`, also backing a new `GET /goals/{id}/export/mass-entry`). Verified for real:
`bb goal export-mass-entry 1` against the live `sv8` master-set goal produced exactly 411 lines,
matching the goal's known needed-card count.

Frontend wiring landed in two pieces once the concurrent app-wide design-system pass (new
`components/ui.tsx`, theming, dark mode) merged to `main`. The tornado chart + "not robust" banner
on `GoalSimulatePage.tsx` survived that redesign's later rewrite intact (it kept `useRunSensitivity`
and the tornado data under the new component library) and shipped as part of that merge.
`GoalDetailPage.tsx`'s rewrite happened against an older copy and dropped the export button
entirely, so it was rebuilt from scratch against the new design system: an "Export shopping list"
button that fetches `GET /goals/{id}/export/mass-entry` and downloads it as a `text/plain` blob.
Verified in a real headless-Chromium browser against the live DB: no console errors, filename
`surging-sparks-master-set-mass-entry.txt`, 410-line output matching the goal's live need list.

15 new backend tests across `test_sim_optimizer.py`, `test_service_simulation_runs.py`,
`test_service_goals.py`, and `test_api_simulate.py`. Full suite: 157 passing (1 slow deselected).
Phase 2 (2.1-2.15) is now fully complete, backend and frontend.

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
by hand or in the next session before trusting the numbers). Phase 2 (2.1-2.15) is entirely done,
backend and frontend (see the notes under Phase 2 above): goal creation and cost model, real
pull-rate profiles, the closed-form and vectorised simulation engines, strategy search/objectives/
persistence, sensitivity analysis with price-basis perturbation and the tornado-chart UI, and
shopping-list export with its "Export shopping list" button -- all verified against the real DB
via the CLI, API, and a real browser. Full suite: 157 passing (1 slow deselected).

Phase 3 (binder designer) is next per the roadmap order above.

No real `box_constraint` data exists yet for exercising `sim/montecarlo.py`'s guarantee code path
against anything but a synthetic fixture -- worth researching one set for this, or accepting
synthetic-only coverage until a source turns up. This doesn't block anything above. Separately,
`data/sealed_map.yaml` still has zero curated `booster_box` entries (only single-pack products
are classified) -- worth curating at least one real booster box for a profiled set so `bb sim
run`'s output includes the product collectors actually ask about.

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
