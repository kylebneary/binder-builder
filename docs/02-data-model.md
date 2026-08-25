# 02 — Data Model

SQLite by default, Postgres-compatible. SQLAlchemy 2.0 typed ORM. Alembic for migrations from the
first commit — do not use `create_all` outside tests.

## The one rule that matters

**Prices attach to a card *variant*, not a card.** tcgcsv returns one price row per
`(productId, subTypeName)`. A single card can be a $1.50 Normal and a $28 Reverse Holofoil at the
same time, and a master-set goal needs both as separate line items. Every part of the system —
ownership, goals, pricing, simulation, binder slots — keys to `card_variant`.

## Entity overview

```
set ──< card ──< card_variant ──< collection_item
 │                    │
 │                    └──< goal_item
 │                    └──< binder_placement
 ├──< sealed_product
 └──< pull_rate_profile ──< pack_slot ──< slot_outcome
                        └──< box_constraint

price_point  (keyed by tcgplayer_product_id + sub_type_name; joined, not FK'd)
```

## Tables

### `set`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| ptcg_set_id | text unique | pokemontcg.io id, e.g. `sv8` |
| tcgplayer_group_id | int unique null | tcgcsv `groupId`; null until mapped |
| name, series | text | |
| printed_total, total | int | `printed_total` excludes secret rares; `total` includes them |
| release_date | date | |
| ptcgo_code | text null | |
| symbol_url, logo_url | text null | |

### `card`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| set_id | FK set | |
| ptcg_card_id | text unique | e.g. `sv8-42` |
| number | text | keep as text — `TG12`, `SV045`, `H31` all exist |
| number_sort | int | derived, for ordering |
| name, supertype, rarity, artist | text | |
| subtypes, types, national_pokedex_numbers | JSON | |
| image_small, image_large | text | |
| dominant_color_lab | JSON null | cached from art, used by Michi auto-layout |

Index `(set_id, number_sort)`.

### `card_variant` ⭐
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| card_id | FK card | |
| variant | enum | `normal`, `holofoil`, `reverse_holofoil`, `first_edition_normal`, `first_edition_holofoil`, `unlimited_holofoil`, `poke_ball_holo`, `master_ball_holo` |
| tcgplayer_product_id | int null | |
| tcgplayer_sub_type_name | text null | verbatim from tcgcsv, e.g. `Reverse Holofoil` |
| is_canonical | bool | the variant counted by a non-master set goal |

Unique `(card_id, variant)`. Index `(tcgplayer_product_id, tcgplayer_sub_type_name)`.

Which variants exist for a card is **derived from the price feed**, not assumed: create a variant
for every `subTypeName` tcgcsv returns for that product ID. This handles era quirks (Pokéball and
Masterball holo patterns in Prismatic Evolutions, 1st Edition in WotC sets) without special-casing.

### `sealed_product`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| set_id | FK set null | null for multi-set products |
| tcgplayer_product_id | int unique | |
| name | text | |
| product_type | enum | `booster_pack`, `booster_bundle`, `blister_3pack`, `booster_box`, `etb`, `ultra_premium_collection`, `special_collection`, `tin`, `case`, `other` |
| packs_per_unit | int null | the field the simulator actually consumes |
| pack_config_id | FK pull_rate_profile null | which pack model these packs follow |
| msrp | numeric(10,2) null | |
| contains_promos | bool | ETBs and collections include non-pack cards; model separately |
| image_url | text null | |

`product_type` and `packs_per_unit` cannot be reliably parsed from names. Ship a curated
`data/sealed_map.yaml` keyed by product ID, and a review queue for unmapped sealed products.

### `price_point`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| tcgplayer_product_id | int | |
| sub_type_name | text | |
| observed_on | date | |
| source | text | `tcgcsv`, `pokemontcg`, `manual` |
| low, mid, high, market, direct_low | numeric(10,2) null | |
| currency | text | `USD` |

Unique `(tcgplayer_product_id, sub_type_name, observed_on, source)`. Index `(observed_on)`.

This is the fact table and will be by far the largest. Partition or prune on a retention policy
(keep daily for 90 days, weekly beyond) once it gets big.

Provide a view `current_price` selecting the latest `observed_on` per key — every read path should
use it rather than re-deriving the max date.

### `collection` / `collection_item`
`collection`: id, name, is_default.

`collection_item`: id, collection_id, **card_variant_id**, quantity, condition
(`NM|LP|MP|HP|DMG`), language, is_graded, grader, grade, acquired_price (numeric null),
acquired_on (date null), storage_location (text null), notes.

Unique `(collection_id, card_variant_id, condition, language, is_graded, grade)` — one row per
distinct holding, `quantity` on top.

### `sealed_holding`
id, collection_id, sealed_product_id, quantity, acquired_price, acquired_on, is_opened.

### `goal` / `goal_item`
`goal`: id, name, goal_type (`set`, `master_set`, `filter`), set_id null, filter_json,
target_condition, created_at.

`goal_item`: goal_id, card_variant_id, required_qty (default 1).

Materialise `goal_item` when the goal is created or the set is updated. Do not evaluate a filter on
every read — the optimizer hits this table hundreds of thousands of times per simulation and it
must be a plain join.

### Pull-rate model
`pull_rate_profile`: id, set_id, name, cards_per_pack, source_urls (JSON), sample_packs int null,
confidence (`high|medium|low`), notes, effective_from, is_default.

`pack_slot`: id, profile_id, slot_index, label.

`slot_outcome`: id, pack_slot_id, rarity (text, matches `card.rarity`), probability (float),
pool_filter_json null.

Probabilities within a slot must sum to 1.0 ± 1e-6 — enforce in a Pydantic validator at load time
and fail loudly, not at simulation time.

`box_constraint`: id, profile_id, rarity, min_per_box, max_per_box, exact_per_box, scope
(`box|case`). This is what breaks pack independence and forces Monte Carlo.

These tables are loaded from `data/pull_rates/*.yaml` by an idempotent sync command. YAML is the
source of truth; the DB is a cache of it.

### `simulation_run`
id, goal_id, created_at, params_json, strategy_json, n_trials, results_json, engine_version.

Persist every run. Reproducibility matters when the answer changes because prices moved rather
than because the model changed — store the price `observed_on` used, and the RNG seed.

### Binder
`binder`: id, name, rows, cols, pages, is_side_loading, gutter_mm, notes.

There is deliberately no `binder_page` table — a page has no attributes of its own beyond its
index, and materialising empty pages just creates rows to keep in sync. Pages are implied by
`binder.pages` and referenced by `page_index` on placements.

`binder_placement`: id, binder_id, page_index, row, col, row_span, col_span, kind
(`card|insert|empty`), card_variant_id null, insert_asset_id null, spans_gutter bool, z_order.

`insert_asset`: id, name, image_path, width_pockets, height_pockets, dpi, source_note.

Placements are rectangles on the pocket grid. Enforce non-overlap in the service layer with an
interval check, and add a DB-level uniqueness guard on the top-left `(binder_id, page_index, row,
col)` as a cheap backstop.

## Migration and idempotency

Every ingest must be re-runnable without duplicating rows: upsert on the natural keys above. The
daily price job in particular will be re-run by hand during development.
