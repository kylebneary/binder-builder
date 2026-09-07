# 05 — Binder Designer Specification

## Physical facts (get these right; everything else is layout logic)

- Standard Pokémon card: **63 × 88 mm** (2.48″ × 3.46″).
- Typical 9-pocket page pocket opening: **~70 × 95 mm** (7 × 9.5 cm).
- Full 9-pocket page art area: **~210 × 285 mm** (21 × 28.5 cm) — near A4, not exactly.
- Common insert spans: 1×1 = 7×9.5 cm; 2×1 (horizontal pair) = 14×9.5 cm; 2×2 = 14×19 cm.
- Grids to support: 3×3 (default), 2×2, 3×4, 4×4.

Store dimensions in millimetres as integers and derive pixels at export time. Do not store pixels.

## What the Michi Method actually is

A curatorial approach that treats **the page — and ideally the two-page spread — as a single
canvas** rather than nine independent pockets. Its characteristic moves:

1. **Custom printed inserts** on matte cardstock, cut to card size, sharing pockets with real cards.
2. **Spanning artwork** — one image stretched across a rectangle of adjacent pockets.
3. **Deliberate negative space** — pockets left empty for balance, which conventional set-order
   binders never do.
4. **Mixed orientation** — landscape inserts against portrait cards.
5. **Side-loading pages**, so a spanning image can cross the gutter between facing pages without
   a pocket lip cutting it. This is a hard requirement for gutter-spanning designs and the tool
   must refuse to place a gutter-spanning insert in a top-loading binder.

Typical page archetypes: single-Pokémon focus, artist retrospective, colour-themed, evolution
line, and full-page art with two or three accent cards.

## Model

The binder is a grid of pockets. Every placement is an axis-aligned rectangle:

```
Placement { page_index, row, col, row_span, col_span, kind, ref, z_order }
kind ∈ {card, insert, empty}
```

A **spread** is a facing pair `(page 2n, page 2n+1)`. For gutter-spanning placements, treat the
spread as a single grid of `rows × (2·cols)` and allow `col` to range across it, flagging
`spans_gutter = true`. Such a placement is stored on the **even (left) page** of the spread, and
its `col` is then in spread coordinates rather than page coordinates; every other placement keeps a
per-page `col` of 0..cols-1. Overlap is therefore checked per spread, not per page, after mapping
both forms into spread coordinates -- see `to_spread_rect` in `backend/app/binder/layout.py`. The renderer draws a gutter allowance (default 6 mm) between the halves so
the print export accounts for the physical gap.

**Invariants** the service layer must enforce:
- placements within a page (or spread) never overlap
- a placement fits inside the grid
- `kind = card` requires a `card_variant_id`; `kind = insert` requires an `insert_asset_id`
- gutter-spanning requires `binder.is_side_loading`

Use an interval-overlap check on rectangles, not a naive per-cell scan, so large binders stay fast.

## Auto-layout modes

### 1. Set order
Fill pockets in card-number order, left-to-right, top-to-bottom. Options: skip reverse holos,
group by rarity, and start each subset on a fresh page. Trivial, and it is what most people
actually want most of the time — build it first.

### 2. Rarity-tiered
Commons and uncommons in bulk pages, then a page per rarity tier ascending, chase cards last.

### 3. Michi-curated (the interesting one)

Input: a pool of cards plus a set of insert templates. Output: a sequence of spreads.

```
1. Cluster the pool into groups of 4–14 cards by the chosen key:
     Pokémon species (national_pokedex_number) | artist | dominant colour | evolution line
2. Allocate each group to one spread; groups too large are split across consecutive spreads.
3. Within a spread, choose a template from the template library whose card-slot count
   best matches the group size.
4. Assign cards to slots by score:
     - the group's highest-value or user-flagged "hero" card goes to the template's hero slot
     - remaining cards ordered by hue angle (or by pokédex number for evolution lines)
5. Score the candidate layout and keep the best of N template/assignment trials.
```

**Layout score** (all terms normalised to 0–1, weights user-adjustable):

```
score = w_sym  · symmetry            # placements mirrored about the spread's vertical axis
      + w_col  · colour_coherence    # 1 - mean pairwise ΔE between adjacent cards in CIELAB
      + w_hero · hero_centrality     # inverse distance of the hero from the spread centre
      + w_fill · fill_balance        # penalise empty pockets clustered on one side
      - w_orph · orphan_penalty      # penalise a group split across non-adjacent spreads
```

Defaults: `w_sym 0.30, w_col 0.25, w_hero 0.20, w_fill 0.15, w_orph 0.10`.

Colour work happens in **CIELAB with ΔE2000**, not RGB — RGB distance does not match perceived
similarity and produces visibly wrong "colour-themed" pages. Extract each card's dominant colour
once via k-means (k=5, take the most saturated large cluster, ignoring the near-white border) and
cache it in `card.dominant_color_lab`.

Template library lives in `data/binder_templates/*.yaml`: a named grid with typed slots
(`hero`, `card`, `insert`, `empty`) and their spans. Ship ~8 hand-designed 3×3 spread templates.

## Export

**Insert PDF** — the print deliverable. Requirements:
- exact physical dimensions, no scaling; embed at ≥300 DPI
- crop marks and a 2 mm bleed on each insert
- inserts laid out on US Letter and A4 sheets, packed to minimise sheet count
- a footer noting the binder name and page index so cut pieces stay identifiable
- reject source images below 300 DPI at the target size with a clear warning rather than
  silently printing something blurry

Build with ReportLab. See the `pdf` skill guidance if available; do not use pypdf for generation.

**Spread preview PNG** — render each spread with card images from the official CDN, pocket
outlines, and the gutter. Used in the UI and for sharing.

**Layout JSON** — full export/import so a layout is portable and diffable.

## UI notes

- Drag and drop with snapping to the pocket grid; a card dropped onto an occupied pocket swaps.
- Show a persistent "not owned" badge on any placement whose card is not in the collection, plus a
  running count. A binder plan that quietly assumes cards you do not have is a bad plan.
- Live spread preview at real aspect ratio. Collectors judge these by eye; a preview that misstates
  proportions is worse than no preview.
- Undo/redo on placements — this is a manual editing surface and will get heavy use.

## Sources

- [A Full Guide to the Michi Method — woahpoke](https://woahpoke.com/michi-method/)
- [The Michi Method for Pokémon binders — xBindr](https://xbindr.com/blog/michi-method)
- [Creating a Binder Preview (with Michi Method) — Elite Fourum](https://www.elitefourum.com/t/creating-a-binder-preview-with-michi-method/60453)
- [What Is the Michi Method? — PocketRune](https://www.pocketrune.com/blog/michi-method)
