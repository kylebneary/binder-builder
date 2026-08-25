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

`bb ingest cards --all` (real-data run, 2026-08-25) got 166 of 174 ptcg sets. These 8 failed
pokemontcg.io across four escalating retry passes and still need a resolution:

- [ ] `smp` — SM Promos
- [ ] `sv1` — **Scarlet & Violet base set** (the owner's single largest CSV entry, 554 rows —
      highest-priority item on this entire list)
- [ ] `sv10`
- [ ] `sve` — Scarlet & Violet Energies
- [ ] `swsh7` — **Evolving Skies** (112 rows in the owner's collection)
- [ ] `xy3`
- [ ] `xy4`
- [ ] `xyp` — XY Promos

`app/ingest/pokemontcg_offline.py` + `scripts/import_offline_cards.py` exist as a manual
fallback (hand-download the pokemontcg.io JSON, import from disk) if retrying the live API keeps
failing. Worth trying the `PokemonTCG/pokemon-tcg-data` GitHub mirror as an alternative source —
not yet attempted.

Two sets (`tk1a`/`tk1b`, `tk2a`/`tk2b` — the EX Trainer Kit half-decks) are **permanently
unmappable**, not just unfetched: tcgcsv sells each pair as one combined product with
overlapping card numbers, and `Set.tcgplayer_group_id` is unique per set. Documented in
`data/set_map.yaml`; not on this backlog because there's nothing to do about it.

## 2. Pull-rate profiles (`data/pull_rates/*.yaml`)

10 done as of 2026-08-25 (see `docs/06-roadmap.md`'s Phase 2 notes for full sourcing detail):
`sv2`, `sv3pt5`, `sv7`, `sv8` (medium confidence, TCGplayer-sourced), `swsh1`, `swsh2`, `swsh3`,
`swsh5`, `swsh6`, `swsh8` (low confidence, thepricedex.com-sourced).

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

- [ ] `pgo` — **Pokémon GO** (507 rows — the owner's single most-collected set by row count).
      No TCGplayer article found; nothing on thepricedex.com either. No source cleared even the
      relaxed "low confidence, real numbers" bar as of 2026-08-25. Also a special product (sold
      only as standalone packs, no booster box) — will need box-less cost-model handling in
      `docs/04-optimizer-spec.md`'s cost math regardless of pull-rate data.
- [ ] `swsh4` — Vivid Voltage (91 rows). Introduces the one-off "Amazing Rare" rarity (6 cards),
      which neither TCGplayer nor thepricedex accounts for. Needs a source that specifically
      covers Amazing Rare odds, or an explicit decision to fold it into another slot with a
      stated (low-confidence) assumption.
- [ ] `sv1` — Scarlet & Violet base (554 rows). Not started — blocked on card ingest (1 above)
      first; can't validate a profile's rarity strings against a set with no ingested cards.

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

- [ ] **SWSH-era Rare Ultra / Rare Rainbow / Rare Secret have zero priced `card_variant` rows.**
      Found while cross-checking pull-rate data (2026-08-25): confirmed across `swsh1`, `swsh2`,
      `swsh3`, `swsh5`, `swsh6`, `swsh8` — the `card` rows exist, but no `card_variant` (and
      therefore no price) was ever ingested for those three rarities specifically. Doesn't block
      pull-rate sync (validation only checks `card.rarity`), but any goal need-list touching
      those cards will show them as unpriced. Root cause not yet investigated — worth checking
      whether tcgcsv's `subTypeName` data for these products was actually missing, or whether the
      ingest adapter mishandled them.
- [ ] `data/sealed_map.yaml`: ~2,405 of ~2,922 tcgcsv sealed products still need hand
      classification (`product_type` / `packs_per_unit`) — the remaining ~517 were mechanically
      classifiable by name pattern. `bb sync sealedmap` prints the review queue. Tracked here as
      a reminder it's large, not because anything changed since the Phase 1 real-data run.

## 4. Deferred to a later phase (not backlog yet — don't start without asking)

- Japanese set pull-rate/pack data (different source: TCGdex, not pokemontcg.io/tcgcsv) —
  Phase 4.4.
- eBay sold-comp data for resale pricing — Phase 4.1, likely a paid API.
- Community pull-rate contribution (users logging their own pack opens) — Phase 4.5. Would
  eventually reduce reliance on third-party aggregators like thepricedex.com for the `low`
  confidence profiles above.
