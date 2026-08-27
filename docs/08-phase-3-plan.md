# 08 — Phase 3 kickoff plan (binder designer)

The execution plan for Phase 3. `docs/05-binder-spec.md` says *what* the binder designer is;
this says *in what order it gets built, on which branches, and what is already done.*
`docs/06-roadmap.md` remains the checkbox source of truth — this document explains the sequencing
behind those checkboxes and should be deleted or archived once Phase 3 closes.

## Context

Phases 0–2 are complete and merged to `main` (157 backend tests passing; tracker and optimizer both
verified against the real ingested DB and in a real browser). Phase 3, the binder designer, is next
per the roadmap order.

Phase 3 is the third pillar from `docs/00-PRD.md`: model a binder as a pocket grid, place cards and
multi-pocket art inserts by drag-and-drop, auto-layout by set order / rarity / Michi-curated, and
export a print-ready insert PDF. Its exit criterion is physical: *the owner has designed a real
binder, printed inserts from the PDF, and they fit the pockets.*

Two findings from reviewing the repo shape this plan:

1. **Significant groundwork already exists but was checked off as "to do."** The binder ORM models
   and their migration are already on `main`, the overlap/bounds half of the layout service is
   implemented and tested, ReportLab and Pillow are already declared dependencies, one spread
   template exists, and `card.dominant_color_lab` is already a column. Task 3.1's checkbox was
   simply stale. Correcting the roadmap is part of this plan, not a side effect of it.
2. **The frontend design system is done and must not be rebuilt.** `frontend/src/components/ui.tsx`
   (450 lines), the dual-theme token system, `CardTile`, `Nav`, and the TanStack Query layer all
   shipped with the Phase 1/2 UI. Parts of it were built *in anticipation of* this phase — the
   `aspect-pocket` Tailwind token is defined and unused, `Segmented` is documented as being for
   "the 3x3 / 3x4 / 2x2 switches", `.hatch` is documented as the "unplaced cards" placeholder, and
   `App.tsx` carries a `TODO(phase-3.3): binder designer canvas` marker as the insertion point.
   All new binder UI composes these: no new visual language, no `dark:` variants, no hex literals.

---

## Step 0 — Roadmap corrections

Landed in the same commit as this document. The corrections to `docs/06-roadmap.md`:

- **3.1 → done.** Its text named a `binder_page` table, but `docs/02-data-model.md` states *"There
  is deliberately no `binder_page` table"* — a page has no attributes beyond its index. The data
  model wins, so `binder_page` is dropped from the task text. The three real tables exist in
  `backend/app/models/binder.py` and are created by the baseline migration
  `c8364ca2a717_baseline_schema.py`.
- **3.2 → amended, still open.** `Rect.overlaps` / `validate_page` (the interval check the spec
  requires) are done and tested. What remains is the gutter/side-loading and `kind`-requires-ref
  invariants, which need the service layer that does not exist yet.
- **3.7 → amended, still open.** `data/binder_templates/hero_center_3x3.yaml` exists and defines the
  file format; ~7 more templates and a loader remain.
- **3.13 → added.** The DB-level uniqueness guard on `(binder_id, page_index, row, col)` that
  `docs/02-data-model.md` specifies as "a cheap backstop" is missing from the baseline migration.
  This is the one genuinely new migration Phase 3 needs.
- **Branch table** — the single `feat/phase-3-binder` row is replaced by the three branches below.

---

## Branching

Phase 3 is split across three branches, mirroring how Phase 1 was deliberately split. The editor
becomes usable and merges before the research-shaped Michi work churns:

| Branch | Covers |
|---|---|
| `feat/phase-3-binder-core` | Step 0, 3.1–3.3, 3.5, 3.11, 3.12, 3.13 |
| `feat/phase-3-binder-export` | 3.4, 3.9, 3.10 |
| `feat/phase-3-binder-michi` | 3.6–3.8 |

---

## Branch 1 — `feat/phase-3-binder-core`

The vertical slice that makes a binder editable. Exit: create a 3×3 binder, drag cards from the
collection into pockets, see the spread at true aspect ratio, undo a mistake, and see a count of
placed-but-not-owned cards.

### Backend

**`backend/app/binder/layout.py`** — extend the existing file; do not rewrite `Rect` /
`validate_page`.

- `validate_placements(placements, binder) -> list[str]` — layers the two missing spec invariants on
  top of the existing `validate_page`: `kind=card` requires `card_variant_id`, `kind=insert` requires
  `insert_asset_id`, and `spans_gutter` requires `binder.is_side_loading`.
- Spread geometry helpers: a spread is `(page 2n, page 2n+1)` validated as one `rows × (2·cols)`
  grid. Gutter-spanning placements are stored on the **even (left) page** with a `col` that ranges
  across the full spread width; non-spanning placements keep per-page `col`. Document this
  convention in the module docstring — it is the single most confusable thing in the phase.
- `auto_layout_set_order(...)` — replace the `**kwargs` stub with a real signature. Fill in
  `number_sort` order, left-to-right, top-to-bottom, with the spec's options: `skip_reverse_holos`,
  `group_by_rarity`, `start_subset_on_new_page`. Rarity-tiered (3.5) is the same generator with a
  different sort key and a page break per tier — write it as one function with a `mode` parameter,
  not two.

**`backend/app/services/binder.py`** — new; mirror the shape of `services/goals.py`.

- `create_binder`, `get_binder`, `list_binders`, `update_binder`, `delete_binder`.
- `get_binder_layout(db, binder_id)` — placements joined to card/variant/image data plus, per
  placement, an `is_owned` flag derived from the default collection (reuse `services/collection.py`'s
  existing holdings query rather than writing a new one) and a `not_owned_count` roll-up. This is
  3.11, and it belongs in the read model, not the UI.
- `set_placement`, `move_placement`, `clear_placement`, `apply_auto_layout` — every mutation runs
  `validate_placements` against the whole affected page/spread and raises before committing.
- `export_layout_json` / `import_layout_json` — the spec's portable, diffable layout format. Cheap
  here, and it is what makes undo/redo and the export branch testable without a browser.

**Migration (3.13)** — one new Alembic revision adding the unique index on
`(binder_id, page_index, row, col)`. No table changes; the tables already exist.

**API** — `backend/app/api/routers/binder.py`, registered in `backend/app/main.py` where the
`# TODO(phase-3): binders` comment sits. Also delete the stale `# TODO(phase-2): simulate` on the
line above it — those endpoints shipped on the goals router. Endpoints:

- `GET/POST /binders`, `GET/PATCH/DELETE /binders/{id}`
- `GET /binders/{id}/layout`
- `PUT /binders/{id}/placements` — batch. One request per user gesture, which is what makes undo a
  single inverse call.
- `DELETE /binders/{id}/placements/{placement_id}`
- `POST /binders/{id}/auto-layout`
- `GET/POST /binders/{id}/layout.json`

Matching Pydantic models go in `backend/app/api/schemas.py` alongside the existing 20.

**CLI** — a `binder` sub-app in `backend/app/cli.py` following the existing six: `bb binder create`,
`bb binder auto-layout <id> --mode set-order --set sv8`, `bb binder show <id>`,
`bb binder export-json <id>`. The CLAUDE.md rule that every capability is reachable without the UI
applies to this phase too.

**Tests** — extend `backend/tests/test_layout.py` (3 tests today) with the gutter/side-loading
refusal, the kind-requires-ref invariants, and spread-grid bounds. New `test_service_binder.py`
(mutation validation, `is_owned` derivation, auto-layout determinism, JSON round-trip) and
`test_api_binder.py`, both using the existing `db` fixture from `conftest.py`.

### Frontend

Add `@dnd-kit/core` + `@dnd-kit/sortable` to `frontend/package.json` — the only new runtime
dependency in this branch. Pointer-based, keyboard-accessible, and it will not fight the
true-aspect-ratio preview the way native HTML5 drag ghosts do.

- `frontend/src/lib/types.ts` — binder types mirroring the new Pydantic schemas, as the file already
  does for the other 20.
- `frontend/src/lib/queries.ts` — `useBinders`, `useBinder`, `useBinderLayout`, `useCreateBinder`,
  `useSetPlacements`, `useAutoLayout`, using the existing `api<T>()` wrapper.
- `frontend/src/pages/BindersPage.tsx` (`/binders`) — list plus create form. Composes `Page`,
  `PageHeader`, `Panel`, `Field`, `Input`, `Select`, `Button` from `ui.tsx`. The grid-size control is
  the existing `Segmented` component, which was written for exactly this.
- `frontend/src/pages/BinderDesignerPage.tsx` (`/binders/:binderId`) — the editor. Spread view of two
  facing pages with a gutter gap; pockets use the existing `aspect-pocket` token, empty pockets use
  `.hatch`. A collection-pool sidebar on the left, drag into pockets, drop-on-occupied swaps.
  Not-owned placements get a `Tag` badge, with the running count from the layout endpoint (3.11).
- `frontend/src/components/BinderPocket.tsx` and `SpreadView.tsx` — new, but built from `CardTile`'s
  existing markup rather than fresh styling.
- Route registration at the `TODO(phase-3.3)` marker in `frontend/src/App.tsx`, and a "Binders" entry
  in the `LINKS` array in `frontend/src/components/Nav.tsx`.
- **Undo/redo (3.12)** — a client-side stack of inverse batch-placement calls held in the designer
  page, keyed to Ctrl/Cmd+Z and Ctrl/Cmd+Shift+Z. Keep it in the page component's state; do not
  reach for a state-management library.

### What landed, and where it differs from the plan above

Branch 1 is complete. Three deliberate deviations, each recorded because the plan text above says
otherwise:

1. **`auto_layout`, not `auto_layout_set_order`.** The plan called for one function with a `mode`
   parameter, which is what shipped -- but keeping the `set_order` name on a function that also
   does `RARITY_TIERED` would misdescribe it, so the stub was renamed rather than filled in.
2. **`@dnd-kit/sortable` was not added.** The pocket grid is a free-form droppable grid and the
   collection pool is not reorderable, so `sortable` had no call site. `@dnd-kit/core` alone is the
   only new runtime dependency.
3. **The spread renders as one grid, not two.** `SpreadView` draws both facing pages as a single
   CSS grid of `2*cols + 1` columns, the middle column being the gutter at `gutter_mm / 70` of a
   pocket width. Two side-by-side grids could not express a rectangle that crosses the gutter,
   which is precisely what the backend's spread coordinates encode.

Beyond the planned surface, `bb binder` also grew `list` and `import-json`, and the layout JSON
carries `ptcg_card_id` + `variant` next to the local `card_variant_id` so an exported layout can
be re-imported into a different database; import resolves by that stable pair and drops placements
for cards the target database does not have.

**Two defects the real data exposed, both fixed.** Neither was reachable from the synthetic
fixtures, which is the argument for the plan's step-2 check against `data/binder_builder.db`:

1. **`RARITY_ORDER` covered 13 of the 38 rarity strings the catalogue actually uses**, so 3,563
   cards (17.6% of 20,479) fell to the alphabetical fallback -- which ranked `Promo` above
   `Hyper Rare` and ordered `LEGEND` against `Radiant Rare` by spelling. The list now covers all
   38 observed values, and `test_every_known_rarity_string_is_ordered` pins them so a future edit
   cannot silently drop one. The real strings are messier than they look: `Rare Ultra` and
   `Ultra Rare` are both live, and `MEGA_ATTACK_RARE` is SCREAMING_SNAKE while everything else is
   title case.
2. **Auto-layout silently omitted cards with no `card_variant` row.** Variants are derived from
   the price feed, so a card the feed has never priced has nothing to place -- 4,808 cards
   catalogue-wide, and disproportionately the chase cards (in Paldea Evolved it is all fourteen
   Wo-Chien / Chi-Yu / Chien-Pao / Ting-Lu ex). `AutoLayoutResult` now carries
   `skipped_no_variant`, surfaced by the CLI, the API and the designer, so the counts add up:
   sv2 reports 265 placed + 14 skipped = its 279 cards. Counting it needed its own query rather
   than `cards_in_set - cards_placed`, since that subtraction also sweeps in cards merely
   filtered out by `canonical_only` -- a caller's choice, not a data gap.

**A third defect, found while clearing the verification artifacts.** `DELETE /binders/{id}` was
leaking rows: SQLite ships with `PRAGMA foreign_keys` OFF and applies it per connection, so all
fifteen `ondelete="CASCADE"` clauses in `app/models` were inert and deleting a binder left its
`binder_placement` rows behind pointing at nothing. Postgres enforces them, so the two supported
engines were behaving differently -- exactly what the Postgres-compatibility rule in CLAUDE.md
exists to prevent. `app/db.py` now exposes `enable_sqlite_foreign_keys` and applies it to the app
engine; the three test fixtures that build their own SQLite engines call it too, or they would go
on passing against behaviour production does not have. Pinned by
`test_deleting_a_binder_removes_its_placements`. The whole suite still passes with enforcement on,
so nothing else in the codebase was relying on the gap.

**Verification status.** `pytest`: 237 passing, 1 slow deselected (baseline was 157), no
regressions. `ruff check` clean on all new code. `npm run build` (tsc + vite) clean.

Against the **real** database (20,479 cards, 174 sets, 1,505 collection items), restored from the
2026-08-27 data package:

- Migration `a1f4c9d7e2b3` applied to it cleanly; `alembic check` reports no drift and
  `PRAGMA integrity_check` is `ok` with row counts unchanged. Note the package README says no
  upgrade is needed -- true at `da02699`, but this branch adds a migration, so one *is* required.
- Auto-layout placed all 249 sv8 canonical variants over 28 pages, and all 265 sv2 canonical
  variants over 30; master mode placed all 441 sv2 variants; `--skip-reverse-holos` dropped
  exactly the 176 reverse holos. Rarity-tiered on `swsh10` produced
  Common -> Uncommon -> Rare -> Rare Holo -> Radiant Rare -> V -> VMAX -> VSTAR, one tier per page.
- **The not-owned cross-check the plan asks for passes exactly.** sv2: 265 placements, 120 not
  owned, against `bb goal need-list` reporting 120 needed -- and 265 - 120 = 145, the number of
  sv2 rows in `collection_item` counted directly. Three independently-derived numbers agree.
- A 265-placement layout round-tripped through JSON with identical placements and not-owned count.
- Over HTTP against a running uvicorn: auto-layout, the 409-with-violations path, and the exact
  swap and inverse-swap batches `BinderDesignerPage` emits -- the swap exchanged the two cards,
  the inverse restored the original layout, and the placement count never moved.

**The interactive browser pass was performed**, driving a real headless Chrome against the real
database (`puppeteer-core` against the machine's installed Chrome, so no browser download and no
new project dependency -- the harness lives outside the repo, see below). Fifteen checks: routes
render, the spread draws 18 pockets at a measured 0.714 aspect ratio (5:7), the pool loads real
cards, drag from pool into a pocket, drag a second into another pocket, drop-onto-occupied swaps,
Ctrl+Z undoes, Ctrl+Shift+Z redoes, the server layout agrees with the DOM, the not-owned badge and
header count render, and auto-layout fills from the UI. Zero uncaught page errors; the only console
error is a 404 for `/favicon.ico`.

**It immediately found two frontend defects that every static check had passed.** Both are fixed:

1. **Cards landed in the wrong pocket.** dnd-kit defaults to `rectIntersection`, which ranks
   droppables by area of overlap with the *dragged element's* rectangle. A pool card tile is far
   wider than a pocket, so it straddled three at once and the leftmost won -- dropping a second
   card onto an empty pocket silently overwrote the first card one pocket away. The captured
   request proves it: aiming at `(row 0, col 1)` posted `{"row":0,"col":0}`. `BinderDesignerPage`
   now uses `pointerWithin` with `closestCenter` as the keyboard-sensor fallback, so the drop
   target is the pocket under the pointer.
2. **Every empty pocket registered the same draggable id.** `BinderPocket` fell back to the
   literal `placement:none` when a pocket held nothing, collapsing seventeen nodes onto one entry
   in dnd-kit's registry. The id is now keyed by cell (`drag:pocket:p:r:c`), which is stable
   whether or not the pocket is occupied.

Neither was reachable from `pytest`, `tsc`, or a vite module-transform check: the batch the client
*sent* was well-formed and the server applied it correctly. Only a real pointer drag could show
that it was the wrong batch.

**The harness was deliberately not kept.** It was a throwaway script driven by `puppeteer-core`
against the machine's installed Chrome, run once and discarded; adding a second dependency tree
and a brittle coordinate-drag suite was judged not worth it for this phase. The consequence is
explicit: **the two frontend fixes above have no regression coverage.** `pointerWithin` collision
detection in `BinderDesignerPage` and the per-cell draggable id in `BinderPocket` are load-bearing
and nothing in the repo will fail if either is reverted. Anyone touching the drag-and-drop wiring
should re-check it in a browser by hand: drag two different cards into two different pockets and
confirm each lands where it was dropped.

---

---

## Branch 2 — `feat/phase-3-binder-export`

The branch that actually satisfies the phase exit criterion, since the exit is a printed sheet.

- **3.4 Insert upload + DPI validation** — `POST /binders/inserts` accepting a multipart image,
  written under `settings.image_cache_dir` (already configured, currently unused). Pillow reads the
  pixel dimensions; compute effective DPI against the target physical size
  (`width_pockets × 70mm` by `height_pockets × 95mm`) and **reject below 300 DPI with an explicit
  message naming the required pixel dimensions** — the spec is emphatic that silently printing
  something blurry is the failure mode to avoid. Store the measured `dpi` on `insert_asset`.
- **3.9 Insert PDF** — implement `export_inserts_pdf` in `backend/app/binder/export.py` with
  ReportLab (already a declared dependency). Exact mm placement with no scaling, 2 mm bleed, crop
  marks, a binder-name/page-index footer, and shelf / first-fit-decreasing packing onto Letter and
  A4. Millimetres are the stored unit; pixels are derived at export time only, per the spec.
- **3.10 Spread preview PNG** — `export_spread_png` with Pillow, drawing card art from the CDN
  (cached to `image_cache_dir`), pocket outlines, and the gutter allowance.
- `GET /binders/{id}/export/inserts.pdf` and `GET /binders/{id}/export/spread/{n}.png`, plus
  `bb binder export-pdf` / `bb binder export-png`.
- Frontend: export buttons on the designer page reusing the blob-download pattern already written in
  `frontend/src/pages/GoalDetailPage.tsx` — do not invent a second download mechanism.
- Tests: assert the PDF's declared page box and the mm offsets of a known insert; assert sub-300-DPI
  uploads are refused. Then **print one sheet and physically check it against a pocket** — that is
  the exit criterion, and no test substitutes for it.

---

## Branch 3 — `feat/phase-3-binder-michi`

The research-shaped work, isolated so its churn cannot block the editor.

- **3.6 Dominant colour** — `bb binder extract-colors --set sv8`: download art to `image_cache_dir`,
  k-means (k=5) with NumPy, take the most saturated large cluster while ignoring the near-white
  border, cache CIELAB into the existing `card.dominant_color_lab` column. No new dependency:
  sRGB→CIELAB and ΔE2000 are hand-written in a new `backend/app/binder/color.py` and unit-tested
  against published reference pairs (the Sharma et al. ΔE2000 test data), which is the cheap way to
  be confident in ~60 lines of tricky arithmetic.
- **3.7 Template library** — a loader for `data/binder_templates/*.yaml`, validating each file with
  Pydantic against the format `hero_center_3x3.yaml` already establishes and checking every template
  for self-overlap on load. Plus ~7 more hand-designed 3×3 spreads covering the spec's archetypes:
  single-Pokémon focus, artist retrospective, colour-themed, evolution line, full-page art.
- **3.8 Michi auto-layout** — cluster → allocate to spreads → pick template by card-slot count →
  assign cards → score, best of N trials, exactly as `docs/05-binder-spec.md` pseudocodes it.
  Implement `score_layout` with the spec's five weighted terms and defaults
  (`w_sym 0.30, w_col 0.25, w_hero 0.20, w_fill 0.15, w_orph 0.10`).
- Tests: each score term individually against a hand-built layout with a known-correct value (a
  perfectly mirrored spread scores 1.0 on symmetry; a group split across non-adjacent spreads incurs
  the orphan penalty), then the composite. Seed the RNG so best-of-N is reproducible.
- Frontend: an auto-layout mode picker (`Segmented`) with the weight sliders the spec calls
  user-adjustable.

---

## Verification

Per branch, the same three-layer check Phases 1 and 2 used:

1. **Tests** — `pytest` from the repo root (config in `pyproject.toml`, `testpaths=backend/tests`).
   Current baseline is 157 passing, 1 slow deselected; no regressions.
2. **CLI against the real DB** — `data/binder_builder.db` holds real ingested sets. Create a binder,
   `bb binder auto-layout` an sv8 set-order layout, and confirm the placement count matches the set's
   card count and that not-owned counts agree with `bb goal need-list`.
3. **Browser against the real DB** — `make dev` (uvicorn + vite), then drive the designer in a real
   headless Chromium: drag a card in, swap two, undo, confirm zero console errors and that
   `npm run build` (tsc + vite) is clean. This is how the Phase 2 UI slices were signed off.

Branch 2 additionally requires the physical check: print `inserts.pdf` at 100% scale (no "fit to
page") and confirm a cut insert fits a real pocket. **Phase 3 is not done until that happens.**

## Out of scope

- The Phase 1 carry-over (real-collection TCGplayer spot-check) and the Phase 2 carry-overs (no real
  `box_constraint` data, no curated `booster_box` entries in `data/sealed_map.yaml`) are unrelated to
  Phase 3 and stay open. See `docs/07-data-backlog.md`.
- Phase 4 items.
