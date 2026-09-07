# 07 — Data Backlog

Running tracker of data this project needs but doesn't have yet. Update this file whenever a
gap is found or closed — it's the checklist to work from before assuming a number is missing
just because nobody's looked, and before re-researching something already ruled out.

Scope note: "sets the owner collects" below means sets that actually appear in the owner's own
collection CSV (`data/pokemon_cards.csv`), ranked by how many rows they have there — that's the
signal used throughout this project to prioritize research effort over the other ~150 ingested
sets nobody currently needs data for.

---

## 1. Card data: sets not yet ingested

**Resolved 2026-08-25.** `bb ingest cards --all` originally got 166 of 174 ptcg sets; the other 8
(`smp`, `sv1`, `sv10`, `sve`, `swsh7`, `xy3`, `xy4`, `xyp`) failed pokemontcg.io across four
escalating retry passes. Live-API retries the same day were still flaky (spot-checked: `sv1` and
`smp` returned 200, `sv10`/`sve`/`swsh7`/`xy4`/`xyp` returned 500/502 on the same pass), so rather
than keep retrying, a new adapter was added: `app/ingest/pokemontcg_github.py`
(`PokemonTcgGithubMirrorSource`), which reads the same card/set JSON from the
`PokemonTCG/pokemon-tcg-data` GitHub mirror (static files, no rate limit, no observed downtime).
All 8 sets fetched cleanly on the first attempt via `bb ingest cards --source github-mirror --set
<id> ...`. `data/set_map.yaml` already had tcgcsv group mappings for all 8 (from the original
research pass); `bb sync setmap` + `bb ingest prices --group <id> ...` linked them and pulled real
prices. Card counts: `smp` 251, `sv1` 258, `sv10` 244, `sve` 16, `swsh7` 237, `xy3` 114, `xy4` 124,
`xyp` 216 — all 174 ptcg sets now ingested. `sv1` in particular (the owner's single largest CSV
entry) is now unblocked for pull-rate authoring (see 2b below).

The live API is worth retrying occasionally since it carries a couple of fields the mirror
doesn't bother with (none used by this project's `CardDTO` today), but `--source github-mirror`
is now the standing fallback for any future flaky-set situation — no more hand-downloading JSON
through `pokemontcg_offline.py` unless the mirror itself is ever down too.

Two sets (`tk1a`/`tk1b`, `tk2a`/`tk2b` — the EX Trainer Kit half-decks) are **permanently
unmappable**, not just unfetched: tcgcsv sells each pair as one combined product with
overlapping card numbers, and `Set.tcgplayer_group_id` is unique per set. Documented in
`data/set_map.yaml`; not on this backlog because there's nothing to do about it.

## 2. Pull-rate profiles (`data/pull_rates/*.yaml`)

12 done as of 2026-08-25 (see `docs/06-roadmap.md`'s Phase 2 notes for full sourcing detail):
`sv2`, `sv3pt5`, `sv7`, `sv8` (medium confidence, TCGplayer-sourced), `pgo`, `swsh1`, `swsh2`,
`swsh3`, `swsh4`, `swsh5`, `swsh6`, `swsh8` (low confidence, thepricedex.com-sourced).

**`swsh4` and `pgo` moved out of "no source found" 2026-08-25.** Both had been marked blocked
after an earlier pass found nothing on thepricedex.com; re-searching turned up a page for each
that the earlier pass had evidently missed. `swsh4` (Vivid Voltage): odds for the one-off
"Amazing Rare" rarity (1 in 17.5 packs) — the specific gap that had blocked it. A second
aggregator (pullrates.com) also covers Vivid Voltage but gives a materially different Amazing
Rare figure (1 in 5) with no disclosed methodology; thepricedex was used for consistency with
this project's other SWSH-era profiles, and the disagreement is called out in the YAML's own
notes rather than silently picking one. `pgo` (Pokémon GO, the owner's single most-collected set
by row count): thepricedex's page covers every rarity in the set, including the set-specific
"Radiant Rare", and — unlike every SWSH-era profile here — reports its *own* reverse-holo odds
directly rather than needing swsh3's borrowed split. See `data/pull_rates/swsh4.yaml` and
`data/pull_rates/pgo.yaml`'s header comments for full sourcing detail and renormalization math.
`pgo` remains a special case in one other way, unrelated to pull rates: it was sold only as
standalone booster packs with no booster-box SKU, so it will still need box-less sealed-cost
handling in `docs/04-optimizer-spec.md`'s cost math before a goal for this set can price a sealed
strategy — not attempted here, since it's a sim/cost-model change, not a data-sourcing one.

### 2a. Blocked on a schema gap, not on research

These have real source data available (or likely findable) but `pull_rate_profile`'s
single-`set_id` design can't represent a hit slot that draws from a *different* set's card pool
— see `docs/02-data-model.md`'s Pull-rate model section for the technical detail. Fixing this
needs a model/schema decision (e.g. an optional `set_id` override on `slot_outcome`, or letting
`pull_rate_profile` span more than one contributing set) before any of these can get a profile:

- [ ] `swsh12pt5` — **Crown Zenith** (175 rows). Hit slot pulls from `swsh12pt5gg` (Galarian
      Gallery). Real 1,900-pack TCGplayer data already found and transcribed in the roadmap
      notes — ready to use the moment the schema supports it.
- [ ] `swsh9` — Brilliant Stars (61 rows). Hit slot pulls from `swsh9tg` (Trainer Gallery).
- [ ] `swsh10` — Astral Radiance (70 rows). Hit slot pulls from `swsh10tg`.
- [ ] `swsh11` — Lost Origin (67 rows). Hit slot pulls from `swsh11tg`.
- [ ] `swsh12` — Silver Tempest (125 rows). Hit slot pulls from `swsh12tg`.
- [ ] `swsh45` — Shining Fates (86 rows). Hit slot pulls from `swsh45sv` (Shiny Vault).

### 2b. Blocked on missing/inadequate source data

- [ ] `sv1` — Scarlet & Violet base (554 rows). No longer blocked on card ingest (1 above is now
      resolved — 258 cards in the DB) — the remaining work is finding a sourced pull-rate article
      the way `sv2`/`sv3pt5`/`sv7`/`sv8` have one, or falling back to the same
      thepricedex.com-style low-confidence treatment used for the SWSH-era sets. Not attempted
      yet.

### 2c. Not yet attempted (owner collects these, no research done)

Older-era sets where pull-rate mechanics differ meaningfully from both the SV-era and SWSH-era
templates already built (different slot structure, different rarity vocabulary) — nobody's
looked yet, not "looked and failed":

- [ ] `sm1` — Sun & Moon (60 rows)
- [ ] `xy12` — Evolutions (41 rows)
- [ ] `sm3` — Burning Shadows (40 rows)
- [ ] `sm4` — Crimson Invasion (36 rows)
- [ ] `sm11` — Unified Minds (33 rows)

"Trick or Trade (2022)" (43 rows in the owner's CSV) is not a distinct ptcg set — it's a
Halloween promo bundle product, not something to build a pull-rate profile for.

### 2d. Not sourced within existing profiles (tracked in each YAML's own notes, repeated here for visibility)

- [ ] Box-level collation guarantees (`box_constraints`) — **zero** of the 10 existing profiles
      have any. No sourced box-guarantee data was found for any of them. This matters: it's the
      entire reason `sim/montecarlo.py` exists instead of just the closed-form
      `sim/analytic.py` (docs/04-optimizer-spec.md) — until at least one profile has a real
      box_constraint, there's no real data to exercise that code path against, only synthetic
      test fixtures.
- [ ] The reverse-holo slot's filler split across Common/Uncommon/Rare (SV-era profiles) or
      Common/Uncommon/Rare/Rare Holo (SWSH-era profiles) is an assumption/approximation in every
      profile, not independently sourced per set.

## 3. Price / variant data gaps

- [ ] **SWSH-era (and `pgo`) Rare Ultra / Rare Rainbow / Rare Secret have zero priced
      `card_variant` rows.** Found while cross-checking pull-rate data (2026-08-25): confirmed
      across `swsh1`, `swsh2`, `swsh3`, `swsh4`, `swsh5`, `swsh6`, `swsh8`, and `pgo` — the
      `card` rows exist, but no `card_variant` (and therefore no price) was ever ingested for
      those three rarities specifically. Doesn't block pull-rate sync (validation only checks
      `card.rarity`), but any goal need-list touching those cards will show them as unpriced.

      **Root cause found and mostly fixed 2026-08-25** (checking `swsh1` "Dhelmise V",
      `card.number` "187", `card.rarity` "Rare Ultra"): tcgcsv does carry the product and a price
      — group 2585 has `productId 208385, "Dhelmise V (Full Art)", Number "187/202", Rarity
      "Ultra Rare"` — but `bb ingest prices` was logging `Skipping variant derivation for card
      swsh1-187: number matched, name differs: 'Dhelmise V' vs 'Dhelmise V Full Art' (confidence
      0.5)`. Not a missing data source: `app/ingest/mapping.py`'s card→product name-matching
      heuristic was correctly refusing to auto-link below its confidence threshold
      (docs/03-data-sources.md: "silent mismatches produce confidently wrong prices, which is
      worse than a gap"), it just didn't know that tcgcsv's `cleanName` appends a special-
      treatment word (e.g. "Full Art") that pokemontcg.io's name never carries. Fixed by adding
      `strip_known_treatment_suffix()` (a finite whitelist: "full art", "alternate full art",
      "rainbow rare", "rainbow", "secret rare", "alternate art secret", "secret", "gold rare",
      "gold", "alternate art", "alt art" — matched as a longest-suffix-wins trailing strip, never
      a generic guess) and wiring it into `match_cards_in_set`'s name comparison, then re-running
      `bb ingest prices` for all 8 affected groups (including `swsh4` group 2701 and `pgo` group
      3064, once the same gap turned up in both while sourcing their pull-rate profiles). Coverage
      for Rare Ultra/Rainbow/Secret across `swsh1/2/3/4/5/6/8` + `pgo` went from **0 of 302** cards
      priced to **291 of 302**.

      **11 cards still unpriced** — the residual name-mismatch patterns are unrelated
      normalization gaps in `normalize_name` itself, not more treatment-word variants: `&`
      becomes the word "and" in tcgcsv's cleanName but is just dropped as punctuation by
      pokemontcg.io's raw name (`"Chili & Cilan & Cress"` vs "Chili and Cilan and Cress"), a
      hyphen becomes a space in tcgcsv but is dropped entirely by pokemontcg.io's normalization
      (`"Cram-o-matic"` vs "Cram o matic" — normalizes to "cramomatic" vs "cram o matic", a real
      word-boundary mismatch, not just a suffix), an accented-character mismatch in `swsh4` and
      `pgo` (`"Pokémon Center Lady"` / `"PokéStop"` vs tcgcsv's ASCII-folded "Pokemon"/"Poke" —
      the "é" is dropped), a bare-number-without-total suffix in `pgo` (`"Pikachu"` vs tcgcsv's
      "Pikachu 27", missing the "/88" tcgcsv usually includes, which `strip_disambiguating_number`
      requires to match), and a treatment word inserted *before* a trailing number rather than
      purely as a suffix (`pgo`'s `"Mewtwo VSTAR"` vs "Mewtwo VSTAR 79 Secret" — stripping "Secret"
      alone still leaves a dangling "79"). All are general `normalize_name`/`mapping.py` fixes,
      not set-specific, and would likely help match rates in other sets too — worth doing as a
      follow-up but deliberately not bundled into this pass since they're a different kind of
      change (core normalization, not a treatment-suffix whitelist) and deserve their own
      verification.
- [ ] `data/sealed_map.yaml`: ~2,405 of ~2,922 tcgcsv sealed products still need hand
      classification (`product_type` / `packs_per_unit`) — the remaining ~517 were mechanically
      classifiable by name pattern. `bb sync sealedmap` prints the review queue. Tracked here as
      a reminder it's large, not because anything changed since the Phase 1 real-data run.

## 4. Collection import fidelity (`data/pokemon_cards.csv`)

Found 2026-09-05 while building the Portfolio holdings table, which surfaced these by putting
per-card quantity and location on screen for the first time.

- [x] **Box/Row/Position were being dropped on import.** The owner's CSV carries physical storage
      coordinates for every row, but `HEADER_ALIASES` in `app/services/csv_import.py` had no entry
      for them and `apply_import` never set `storage_location`, so "where is this card?" was
      unanswerable. Fixed: the three columns are now detected and composed into
      `storage_location` (`Box 1 - A3`). **The existing rows predate the fix and are still
      unlocated** — a re-import backfills them.

- [ ] **The collection is undercounted roughly 2:1, and this affects portfolio value.** The CSV
      holds one row per physical card, and 849 `(set, number, condition)` keys appear more than
      once — 15 rows of Pokémon GO #32, for instance. `upsert_collection_item` *sets* quantity
      rather than summing, so every duplicate collapses to a single row of quantity 1: **1,761
      cards silently dropped.** The database reports 1,486 cards / $642.57 against ~3,428 matched
      CSV rows. The fix is to aggregate rows sharing a natural key when the file has no quantity
      column, while continuing to trust an explicit quantity column where one exists (Collectr
      and Deckbox exports have one; this file does not). Not done because it materially restates
      the owner's portfolio value and that should be a deliberate call.

- [ ] **A re-import would also add ~320 holdings**, not just backfill locations: those rows failed
      the original import with `no_variant` because their sets had no prices ingested at the time.
      Measured on a copy: 1,505 -> 1,825 rows, 0 -> 1,803 locations.

- [ ] **No cost basis exists.** `acquired_price` is null on all 1,505 rows because the CSV has no
      price column, so the Portfolio page's "Cost basis $0.00" and "Unrealized gain" (which just
      restates market value) are not meaningful. Either source acquisition prices or drop those
      two tiles. Note the data-package README claims the collection ships "with acquired prices";
      it does not.

## 5. Deferred to a later phase (not backlog yet — don't start without asking)

- Japanese set pull-rate/pack data (different source: TCGdex, not pokemontcg.io/tcgcsv) —
  Phase 4.4.
- eBay sold-comp data for resale pricing — Phase 4.1, likely a paid API.
- Community pull-rate contribution (users logging their own pack opens) — Phase 4.5. Would
  eventually reduce reliance on third-party aggregators like thepricedex.com for the `low`
  confidence profiles above.
