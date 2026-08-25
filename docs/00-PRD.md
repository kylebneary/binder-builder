# 00 — Product Requirements

## Problem

Completing a Pokémon TCG set is a purchasing problem disguised as a hobby. A collector faces a
menu of options — buy the ~200 missing cards individually, open sealed product and hope, or some
mix — and has no good way to compare them. Existing tools solve half of it: Collectr and TCG
Collector track what you own; pull-rate blogs quote odds; EV calculators tell you a booster box is
"worth" $X. Nothing connects *what you already own* to *what a pack is worth to you specifically*.

That last point is the whole thesis. A booster box's market EV is a fixed number. Its **completion
EV** is personal: if you already own every Illustration Rare in the set, the packs that contain
them are worth their resale value to you, not their sticker price. The gap between those two
numbers is where the actual decision lives, and no existing tool computes it.

## Users

Primary and only user for v1: the repo owner, a set collector who buys deliberately and wants the
math to be right. Design for a single local user; leave the seams for multi-user but do not build
auth in v1.

## Goals

1. Know exactly what is owned, at what variant and condition, and what it is worth.
2. Define a collecting goal ("master set of Surging Sparks", "every Charizard illustration rare")
   and see the remaining cost, updated daily.
3. Get a defensible answer to "singles, sealed, or both?" with a cost distribution — not a point
   estimate — and see the assumptions behind it.
4. Plan a binder that is worth looking at, including Michi-method spreads, and print the inserts.

## Non-goals (v1)

- Mobile apps. Responsive web only.
- Grading/PSA population data, price *prediction*, or investment advice.
- Games other than Pokémon. The data model should not actively prevent it; nothing more.
- Buying anything. The tool produces a shopping list; the user buys it.
- Multi-user accounts, sharing, social features.

## Feature requirements

### P1 — Collection tracker

| ID | Requirement |
|----|-------------|
| T1 | Import the full Pokémon card database (all sets, all cards) and refresh it on demand. |
| T2 | Browse by set with a visual grid; filter by rarity, type, artist, owned/needed. |
| T3 | Mark cards owned per **variant** (Normal / Holofoil / Reverse Holofoil / 1st Ed), with quantity, condition, optional purchase price and date. |
| T4 | Fast bulk entry: keyboard-driven "walk the set in number order and mark what you have". This is the single most important UX detail — collectors abandon trackers that make entry slow. |
| T5 | Import from CSV (Collectr, TCG Collector, Deckbox exports) and export to CSV. |
| T6 | Portfolio value: current market value, cost basis, unrealized gain, per set and total. |
| T7 | Track sealed product holdings alongside singles. |
| T8 | Daily price snapshots so value history is a real time series, not a single reading. |

### P2 — Completion optimizer

| ID | Requirement |
|----|-------------|
| O1 | Define a goal: a set, a master set (includes reverse holos), or a saved filter over cards. |
| O2 | Compute the singles-only cost to complete, accounting for shipping and seller consolidation. |
| O3 | Model any sealed product as a distribution over pulls, using a per-set pull-rate profile. |
| O4 | Monte Carlo simulate "buy *k* of product P, then fill the rest with singles" and return the **distribution** of total net cost, net of the resale value of duplicates. |
| O5 | Search over strategies (quantities and mixes of sealed products) and rank them by the user's chosen objective. |
| O6 | Objectives: minimise expected net cost; minimise cost at the 90th percentile (risk-averse); maximise completion percentage under a fixed budget. |
| O7 | Show the assumptions and their sources on the same screen as the answer, and let the user edit them (pack price, fee rate, dupe liquidation haircut, shipping model). |
| O8 | Produce a shopping list of singles to buy, sorted by price, exportable as a TCGplayer Mass Entry list. |

### P3 — Binder designer

| ID | Requirement |
|----|-------------|
| B1 | Model a binder: pocket grid (3×3 default; 2×2, 3×4, 4×4 supported), page count, side- or top-loading. |
| B2 | Place cards from the collection into pockets by drag-and-drop, with a live spread preview. |
| B3 | Place **inserts**: art panels spanning a w×h rectangle of pockets, including spanning the gutter across a facing-page spread (the signature Michi move, which requires side-loading pages). |
| B4 | Auto-layout modes: set order; rarity-tiered; and Michi-curated (grouped by Pokémon/artist/colour with symmetric negative space). |
| B5 | Export a print-ready PDF of inserts at exact physical dimensions, and a PNG preview of each spread. |
| B6 | Flag binder slots whose cards are not actually owned, so the plan and the collection stay honest. |

## Success criteria

The project has succeeded when the owner can, in under five minutes: load a set, mark what they
own, and get a ranked list of purchase strategies with a cost distribution and a stated confidence
— and when the resulting purchase decision is one they would defend to another collector.

## Key risks

| Risk | Mitigation |
|------|------------|
| Pull rates for English sets are unpublished; all figures are community estimates with wide error bars. | Treat them as first-class versioned data with sources and confidence. Report percentiles, never a single number. Let users run sensitivity analysis. |
| Price data terms of use may change; tcgcsv is a volunteer project. | Adapter interface with more than one implementation from day one. Snapshots persist locally, so the tool degrades to stale-but-working. |
| Optimizer complexity balloons before the tracker is usable. | Phase gate: the tracker ships and gets used before optimizer work begins. |
| The honest answer is usually "buy singles". | That *is* the product. Quantifying how much sealed loses by — and surfacing the sets where it does not — is the value. |
