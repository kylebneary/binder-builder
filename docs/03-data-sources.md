# 03 — Data Sources

Verified 2026-08-25. Every endpoint below was queried live and the schemas are transcribed from
actual responses, not from documentation.

## Decision summary

| Need | Primary | Fallback |
|------|---------|----------|
| Card & set metadata | **pokemontcg.io v2** | TCGdex |
| Single-card prices (USD) | **tcgcsv.com** (TCGplayer mirror) | pokemontcg.io embedded prices |
| Sealed product catalogue & prices | **tcgcsv.com** — the only free source that has this | manual entry |
| Pull rates | **Hand-curated YAML** in `data/pull_rates/`, sourced from community aggregations | user override |

The architecture requires a `PriceSource` adapter interface (`backend/app/ingest/base.py`) so a
paid API can be added later by dropping in one file. See "Paid options" below.

---

## 1. tcgcsv.com — primary price source ⭐

A free mirror of TCGplayer's API data, published as JSON and CSV. **This is the backbone of the
project** because it is the only free source that carries sealed products with prices.

- Cost: free. Voluntary Patreon support.
- Update cadence: once daily, ~20:00 UTC. Ingest job should run at 20:30 UTC. Never poll faster.
- Pokémon category ID: **3**. 218 groups (sets/products) as of 2026-08-25.
- **Requires a custom `User-Agent` header.** The default header sent by httpx/requests/curl's
  libcurl UA is blocked outright with `401 Unauthorized` and a plain-text body asking for
  `User-Agent: Your-Application-Name/X.Y.Z` (see the usage guidelines linked in that response).
  Discovered live during this session -- not documented anywhere above before now. Every
  `TcgCsvClient` request in `backend/app/ingest/tcgcsv.py` sets one.

### Endpoints

```
https://tcgcsv.com/tcgplayer/categories
https://tcgcsv.com/tcgplayer/3/groups
https://tcgcsv.com/tcgplayer/3/{groupId}/products
https://tcgcsv.com/tcgplayer/3/{groupId}/prices
```
Each also exists as `.csv`. Archived daily bundles are available for backfilling history.

### Verified schemas

**Group** (a set or product line):
```json
{"groupId": 24722, "name": "ME: 30th Celebration", "abbreviation": "30C",
 "isSupplemental": false, "publishedOn": "2026-09-16T00:00:00",
 "modifiedOn": "...", "categoryId": 3}
```

**Product** — singles and sealed live in the same list; distinguish them by `extendedData`:
```json
{"productId": 696676, "name": "Greninja ex", "cleanName": "Greninja ex",
 "imageUrl": "https://tcgplayer-cdn.tcgplayer.com/product/696676_200w.jpg",
 "categoryId": 3, "groupId": 24722,
 "url": "https://www.tcgplayer.com/product/696676/...",
 "modifiedOn": "2026-06-05T17:27:26.92", "imageCount": 1,
 "presaleInfo": {"isPresale": true, "releasedOn": "2026-09-16T00:00:00", "note": "..."},
 "extendedData": [
   {"name": "Number", "displayName": "Card Number", "value": "021/128"},
   {"name": "Rarity", "displayName": "Rarity", "value": "Double Rare"}]}
```

**Sealed products have no `Number`/`Rarity` in `extendedData`** — that absence is the reliable
classifier. Do not classify on the product name; naming is inconsistent across eras.

```json
{"productId": 704143, "name": "30th Celebration Elite Trainer Box",
 "groupId": 24722, "extendedData": [{"name": "CardText", ...}]}
```

**Price** — note there is one record per `(productId, subTypeName)`:
```json
{"productId": 696613, "lowPrice": 16.41, "midPrice": 20.93, "highPrice": 155.49,
 "marketPrice": 16.44, "directLowPrice": null, "subTypeName": "Normal"}
```

`subTypeName` values seen: `Normal`, `Holofoil`, `Reverse Holofoil`, `1st Edition Holofoil`,
`1st Edition Normal`, `Unlimited Holofoil`. **This field is why the data model keys prices to a
card *variant*, not a card.** A card with a $2 Normal and a $30 Reverse Holofoil is one product ID
with two price rows, and a master-set goal needs both.

### Ingest notes

- `marketPrice` is TCGplayer's computed market value and is the right default for portfolio
  valuation. `lowPrice` is the right default for *acquisition cost* modelling, but it represents a
  single lowest listing that may be a poor-condition or high-shipping outlier — the optimizer
  should default to `marketPrice` with a user-adjustable blend toward `lowPrice`.
- `directLowPrice` is frequently `null`. Handle it.
- Nulls appear across the board for presale and out-of-print items.
- Full Pokémon daily pull is roughly 20–40 MB of JSON. Store snapshots in the DB; do not commit.

---

## 2. pokemontcg.io — card metadata

REST, JSON, free, no key required (heavily rate-limited without one; register at the developer
portal for a key). v2 is current; v1 is dead.

```
GET https://api.pokemontcg.io/v2/sets
GET https://api.pokemontcg.io/v2/cards?q=set.id:sv8&pageSize=250
```

Card objects carry: `id`, `name`, `supertype`, `subtypes`, `hp`, `types`, `evolvesFrom`,
`abilities`, `attacks`, `weaknesses`, `resistances`, `retreatCost`, `set`, `number`, `artist`,
`rarity`, `regulationMark`, `flavorText`, `nationalPokedexNumbers`, `legalities`,
`images.{small,large}`.

It also embeds `tcgplayer.prices.{normal,holofoil,reverseHolofoil,1stEditionHolofoil,
1stEditionNormal}.{low,mid,high,market,directLow}` and `cardmarket.prices.*` (EUR). These are
useful as a fallback but update less predictably than tcgcsv, and there is no sealed coverage.

**Use it for:** card identity, rarity, artist, images, Pokédex numbers — everything the optimizer
needs to build rarity pools and the binder needs to render.

**Caveat:** it is a volunteer project with occasional multi-day outages. Cache aggressively; the
card database changes only when a set releases.

### Fallback: the `pokemontcg-data` GitHub mirror

When the live API is hard-down for a specific set across retries (observed 2026-08-25: 8 sets
failed four escalating retry passes with 500/502s), use
`app/ingest/pokemontcg_github.py`'s `PokemonTcgGithubMirrorSource` instead of waiting it out —
`bb ingest cards --source github-mirror --set <id>`. The `PokemonTCG/pokemon-tcg-data` GitHub repo
publishes the identical card/set data as static JSON checked into git:

```
GET https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master/sets/en.json
GET https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master/cards/en/{ptcg_set_id}.json
```

Same fields as the live API's card object, with two shape differences the adapter accounts for:
the files are bare JSON arrays (no `{"data": [...]}` envelope, no pagination), and card objects
don't embed a `set` object (so the adapter falls back to the requested `set_ref`). No rate limit,
no observed downtime, since it's just raw file serving off GitHub's CDN. Not a permanent
replacement for the live API — it won't have a set on the day it's revealed if the mirror hasn't
synced yet — but a reliable fallback for exactly the "specific set is stuck failing" case.
`app/ingest/pokemontcg_offline.py` (hand-download JSON, import from disk) still exists as a
last-resort fallback if the mirror itself is ever unavailable too.

### Joining pokemontcg.io to tcgcsv

There is no shared key. Match on `(set, card number, name)`:
1. Map pokemontcg.io `set.id` → tcgcsv `groupId` via a curated table (`data/set_map.yaml`),
   seeded by fuzzy-matching set names and release dates, then hand-corrected. There are ~170
   English sets; this is a bounded one-time cost.
2. Within a set, match card `number` against `extendedData.Number` (strip the `/128` suffix and
   leading zeros), then verify with a normalised name comparison. tcgcsv's `cleanName` sometimes
   appends a special-treatment word to disambiguate a card from a same-named regular print in the
   same set (e.g. "Dhelmise V" → cleanName "Dhelmise V Full Art"); `app/ingest/mapping.py`'s
   `strip_known_treatment_suffix()` undoes a known, finite whitelist of these (found 2026-08-25
   while investigating why SWSH-era Rare Ultra/Rainbow/Secret cards had zero priced variants —
   see `docs/07-data-backlog.md` §3). It does not (yet) handle `&`-vs-"and" or hyphen-vs-space
   differences in the base name itself — a handful of cards per set still fall through to the
   review queue on those.
3. Log unmatched cards to a review queue. Promos and special subsets will need manual mapping.

Do not skip step 3. Silent mismatches produce confidently wrong prices, which is worse than a gap.

---

## 3. TCGdex — metadata fallback

Open-source, multilingual (useful if Japanese sets are ever added), GraphQL and REST, free.
Weaker English price coverage. Keep as the secondary metadata adapter.

---

## 4. Pull rates — no free API exists

**There is no authoritative machine-readable source.** The Pokémon Company does not publish odds
for English product. Every figure in circulation is derived from community case-opening logs.
Aggregators (pullrates.gg, pullmarket.io, pokeloot.io, archivedrops.com) publish estimates as HTML
with no API and no stated sample sizes.

The project therefore treats pull rates as **curated data, not fetched data**: versioned YAML in
`data/pull_rates/`, one file per set, each carrying source URLs, sample size where known, and a
confidence rating. See `docs/04-optimizer-spec.md` for the schema and `data/pull_rates/_TEMPLATE.yaml`.

### Established structure of a modern (Scarlet & Violet era) English pack

10 cards:

| Slot | Contents |
|------|----------|
| 1–4 | Common |
| 5–7 | Uncommon |
| 8 | Reverse holo of any Common / Uncommon / Rare |
| 9 | Rare or Holo Rare |
| 10 | "Hit slot" — Double Rare, Ultra Rare, Illustration Rare, Special Illustration Rare, Hyper Rare, or ACE SPEC |

Community-estimated hit-slot frequencies, modern SV-era baseline:

| Rarity | Approx. rate |
|--------|--------------|
| Double Rare (ex) | ~1 in 5 packs |
| Ultra Rare | ~1 in 9 packs |
| Illustration Rare | ~1 in 10–12 packs |
| Special Illustration Rare | 1 in 32 to 1 in 86 (varies enormously by set) |
| Hyper Rare / Gold | ~1 in 100 |

The SIR spread is the important one: Prismatic Evolutions sat near 1 in 45 while Surging Sparks was
closer to 1 in 85–90. **Set-specific profiles are mandatory; a global default will be wrong by a
factor of two on the exact cards that dominate completion cost.**

Older eras differ structurally (11-card packs, no reverse holo before 2002, different hit
distributions). The profile schema must express slot counts per set rather than assuming ten.

---

## 5. Paid options (adapters to add later, not now)

| Service | Offers | Notes |
|---------|--------|-------|
| PokemonPriceTracker | Daily TCGplayer + eBay sold data, sealed tracking, EV endpoints | Free tier exists; the eBay sold-comp data is the genuinely differentiated part |
| tcgapi.dev | Multi-game daily market prices, cards + sealed | |
| TCGplayer official API | Authoritative, real-time | Partner-gated; application required and not generally granted to hobby projects |

**eBay sold comps are the one thing worth paying for eventually.** TCGplayer market price lags
actual transaction prices on volatile cards, and duplicate-liquidation modelling in the optimizer
is only as good as its resale price input.

---

## Legal / etiquette

- tcgcsv redistributes TCGplayer data by arrangement; use it as published and credit it.
- Do not scrape TCGplayer, eBay, or Cardmarket HTML from this project.
- Card images are © The Pokémon Company. Fine for personal use and hotlinking from the official
  CDNs; do not redistribute a bundled image archive.
- The binder module lets users import their own art for inserts. Do not ship copyrighted art in
  the repo, and note in the UI that printed inserts are for personal use.

## Sources

- [tcgcsv.com](https://tcgcsv.com/)
- [Pokémon TCG API docs](https://docs.pokemontcg.io/)
- [Pokémon TCG API card object](https://docs.pokemontcg.io/api-reference/cards/card-object)
- [TCGdex](https://tcgdex.dev/)
- [pullmarket.io — pack pull rates](https://pullmarket.io/learn/pokemon-pack-pull-rates)
- [pullrates.gg](https://www.pullrates.gg/)
- [PokemonPriceTracker API](https://www.pokemonpricetracker.com/pokemon-card-price-api)
- [tcgapi.dev](https://tcgapi.dev/)
