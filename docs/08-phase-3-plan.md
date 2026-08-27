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
