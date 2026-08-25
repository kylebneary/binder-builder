# 04 — Completion Optimizer Specification

The core of the project. Read this fully before writing anything in `backend/app/sim/`.

## The question being answered

> I want to complete goal *G*. I already own *O*. Given today's prices, what purchasing strategy
> minimises what I will actually spend, and how uncertain is that number?

Note "actually spend", not "spend on packs". A strategy that opens sealed product yields duplicates
and off-goal cards that can be resold. The optimizer works in **net cost**.

## Definitions

- *G* — the goal, a set of `(card_variant, required_qty)` rows.
- *O* — current holdings.
- *N = G \ O* — the need list.
- `p_single(v)` — acquisition price of variant *v*. Default `market`; user can blend toward `low`.
- `p_resale(v)` — what the user would net reselling *v*. See "Liquidation model".
- A **strategy** *S* — a multiset of sealed products to buy, e.g. `{booster_box × 2, etb × 1}`.
  *S = ∅* is the singles-only strategy and is always evaluated as the baseline.

## Cost model

```
NetCost(S) = SealedCost(S)
           + SinglesCost(N')                 # what's still missing after opening S
           - Liquidation(D)                  # duplicates and off-goal cards from S
```
where `N'` and `D` are random variables determined by simulation.

### SealedCost
Sum of current market price per unit, plus `sealed_shipping` (default $0 — boxes usually ship
free), plus optional `sales_tax_rate`.

### SinglesCost — do not model this as a naive sum

Summing 180 card prices understates the real bill badly. Model it as:

```
SinglesCost(N') = Σ_{v ∈ N'} p_single(v)  +  ShippingCost(|N'|)
```

`ShippingCost` is configurable, defaulting to a **seller-consolidation model**:

```
orders   = ceil(|N'| / cards_per_order)     # cards_per_order default 12
shipping = orders × shipping_per_order      # default $1.29 (TCGplayer standard)
```

This approximates TCGplayer's Mass Entry optimizer, which consolidates a want list across the
fewest sellers. It is deliberately crude — expose `cards_per_order` and `shipping_per_order` in the
UI and note in the docs that a 200-card want list realistically lands 10–20 orders.

A second refinement worth building in Phase 2b: cards below a `bulk_threshold` (default $0.35) are
effectively unobtainable individually at a sane per-card cost, because shipping dominates. Offer a
`bulk_lot_price` parameter — the user can buy the commons/uncommons as a bulk lot — and let the
optimizer route cheap cards there.

### Liquidation model

A duplicate is not worth its market price. Net of fees, shipping supplies, and effort:

```
p_resale(v) = p_single(v) × liquidation_rate   if p_single(v) ≥ resale_floor
            = 0                                otherwise
```

Defaults: `liquidation_rate = 0.70` (TCGplayer takes ~10.25–12.5% plus payment processing, and
shipping supplies eat the rest on low-value cards), `resale_floor = $2.00` (below this, the card is
bulk and realistically nets nothing).

These two parameters swing the answer more than almost anything else. Surface them prominently and
run sensitivity on them by default.

## The simulation engine

### Why Monte Carlo and not closed form

The closed form is tempting. For a card *v* in rarity pool *R* with per-pack probability
`p_v = P(slot yields R) / |R|`, after *k* packs:

```
P(v never pulled) = (1 - p_v)^k
E[SinglesCost] = Σ_v p_single(v) · (1 - p_v)^k
```

**Implement this — as `sim/analytic.py`, used for fast UI previews and as a unit-test oracle.** But
it is not the primary engine, because it assumes independence across packs, and that assumption is
false in exactly the cases that matter:

1. **Box guarantees.** Sealed boxes are collated. A 36-pack box that reliably contains 4–5
   Illustration Rares is sampling without replacement, not 36 independent Bernoulli draws. The
   variance of the closed form is badly wrong even when the mean is close.
2. **Within-box duplicate suppression.** Collation tends to avoid repeating the same hit inside a
   box, which materially improves set-completion odds versus independent draws.
3. The user's actual question is often about tails ("what's the 90th-percentile cost?"), and the
   analytic form gives no honest distribution once (1) and (2) are in play.

### Algorithm

```
simulate(strategy S, goal G, owned O, params, n_trials, seed) -> Distribution

for trial in 1..n_trials:                    # vectorise over trials with NumPy
    pulled = multiset()
    for each sealed unit u in S:
        for each box b in u:
            packs = draw_box(b, profile)     # honours box_constraint
            pulled += packs
    still_needed = G - O - pulled
    dupes        = pulled - (G - O)          # everything not consumed by the goal
    cost = SealedCost(S)
         + SinglesCost(still_needed)
         - Liquidation(dupes)
    record(cost, completion_pct_before_singles)

return {mean, sd, p10, p50, p90, p95,
        P(complete from sealed alone),
        E[cards still needed],
        histogram}
```

### `draw_box` — respecting collation

1. Draw the box's guaranteed hits first, per `box_constraint`: for each constrained rarity, sample
   `exact_per_box` (or uniform on `[min, max]`) cards **without replacement** from that rarity pool.
2. Assign the guaranteed hits to distinct packs.
3. Fill remaining slots in remaining packs by sampling `slot_outcome` distributions, renormalised
   to exclude already-satisfied guarantees.
4. Within-pack, sample the specific card uniformly from the rarity pool unless
   `slot_outcome.pool_filter_json` narrows it.

Uniform-within-rarity is a modelling assumption and must be labelled as one in the UI. It is
approximately right for modern sets and clearly wrong for older ones with known short prints.
Support a per-card `weight` override in the profile YAML for when a set has documented short prints.

### Performance target

100,000 trials of a 36-pack box on a set of ~200 cards in under two seconds. That requires
representing the card pool as integer indices into NumPy arrays and drawing all trials at once with
`rng.choice` on a `(n_trials, n_packs)` shaped operation — not a Python loop per pack. Budget the
work accordingly; a naive implementation is 100× too slow and will make the UI unusable.

## Strategy search

The decision variable is a small vector of non-negative integers (how many of each sealed product).

- **1–2 product types:** exhaustive grid search over `k = 0 … k_max`, where `k_max` is the quantity
  at which expected completion exceeds 99% or the budget cap binds. Simulate each point. This is
  typically fewer than 400 simulations and is the right answer for v1.
- **3+ product types:** greedy marginal analysis — repeatedly add the unit with the best marginal
  net-cost reduction until no unit improves the objective. Optionally polish with local search
  (±1 on each product). Do not reach for an MIP solver; the objective is a simulation output and is
  not linear.

Cache aggressively: results depend on `(goal, owned, price date, profile version, params)`. Hash
that tuple and memoise.

## Objectives

| Objective | Selects |
|---|---|
| `min_expected_cost` | argmin `E[NetCost]` |
| `min_p90_cost` | argmin `P90[NetCost]` — the risk-averse choice, and usually more decision-relevant |
| `max_completion_under_budget` | argmax `E[completion %]` s.t. `P(cost ≤ budget) ≥ 0.9` |
| `min_cost_for_target_completion` | argmin cost s.t. `P(completion ≥ target) ≥ confidence` |

Always show the singles-only baseline alongside the winner, with the delta. If singles win —
which they usually will — say so plainly and show by how much.

## Sensitivity analysis (ship this, it is not optional)

Every result must come with a tornado chart over:

- pull rates for the top-3 cost-driving rarities (±50%)
- `liquidation_rate` (0.5 → 0.85)
- pack/box price (±20%)
- `p_single` basis (`low` vs `market` vs `high`)

If the recommendation flips under a plausible pull-rate perturbation, the UI must say the
recommendation is not robust. Given that pull rates are community estimates with unknown sample
sizes, this will happen often, and hiding it would make the tool dishonest.

## Pull-rate profile YAML

```yaml
set: sv8                        # ptcg_set_id
name: "Surging Sparks - standard booster"
cards_per_pack: 10
confidence: medium
sample_packs: 4200
source_urls:
  - https://pullmarket.io/learn/pokemon-pack-pull-rates
notes: >
  Hit-slot rates aggregated from community case logs. SIR rate is the least certain figure
  and drives most of the completion cost for this set.

slots:
  - index: 1
    label: common
    repeat: 4
    outcomes: [{rarity: "Common", probability: 1.0}]
  - index: 5
    label: uncommon
    repeat: 3
    outcomes: [{rarity: "Uncommon", probability: 1.0}]
  - index: 8
    label: reverse_holo
    repeat: 1
    outcomes:
      - {rarity: "Common",   probability: 0.55, variant: reverse_holofoil}
      - {rarity: "Uncommon", probability: 0.35, variant: reverse_holofoil}
      - {rarity: "Rare",     probability: 0.10, variant: reverse_holofoil}
  - index: 9
    label: rare
    repeat: 1
    outcomes:
      - {rarity: "Rare",      probability: 0.75}
      - {rarity: "Rare Holo", probability: 0.25}
  - index: 10
    label: hit
    repeat: 1
    outcomes:
      - {rarity: "Double Rare",               probability: 0.200}
      - {rarity: "Ultra Rare",                probability: 0.111}
      - {rarity: "Illustration Rare",         probability: 0.091}
      - {rarity: "Special Illustration Rare", probability: 0.012}
      - {rarity: "Hyper Rare",                probability: 0.010}
      - {rarity: "Rare",                      probability: 0.576}   # no-hit filler

box_constraints:
  - rarity: "Special Illustration Rare"
    scope: box
    min_per_box: 0
    max_per_box: 2
```

Validation rules, enforced at load:
- outcome probabilities per slot sum to 1.0 ± 1e-6
- every `rarity` string matches at least one card in the set (else the pool is empty and the
  simulator silently produces nothing — fail loudly instead)
- `sum(repeat) == cards_per_pack`
- `variant` defaults to `normal`; the reverse-holo slot must set `reverse_holofoil` or master-set
  goals will never complete

## Testing

Minimum bar before this module is considered done:

1. **Analytic agreement.** With all `box_constraints` removed, Monte Carlo means must match
   `sim/analytic.py` within Monte Carlo error (3 SE) across a range of *k*.
2. **Coupon-collector sanity.** A synthetic set of *n* equally likely cards, one per pack, must
   reproduce `n·H_n` expected packs to complete, within tolerance.
3. **Degenerate cases.** Empty need list → cost 0. Owning nothing and buying nothing → singles cost
   equals the plain sum plus shipping.
4. **Determinism.** Same seed → same result, byte for byte.
5. **Box constraints bite.** With `exact_per_box: 4`, every simulated box contains exactly 4.
6. **Monotonicity.** Expected remaining-singles cost is non-increasing in *k*.

## Expected finding, stated up front

For most modern sets, singles will win, often by 40–70%. Sealed product is priced above its EV
because people enjoy opening it, and completion EV is *lower* than market EV for any collector who
already owns part of the set. The interesting output is the exceptions:

- master-set goals where reverse holos are expensive as singles but common in packs
- sets with cheap boxes relative to a small, expensive chase pool
- collectors starting from zero on a freshly released set, where singles carry a release premium

Design the UI to make these findings legible rather than burying them in a number.
