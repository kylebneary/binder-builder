"""Michi-curated auto-layout: cluster, allocate, template, assign, score (roadmap 3.8).

Follows the pseudocode in docs/05-binder-spec.md. The interesting part is the scoring function,
because "does this spread look good" is a taste judgement and the only honest thing to do is make
the taste explicit, weighted, and adjustable.

Pure: no ORM, no filesystem, no network. Callers hand in `MichiCard`s and a template library and
get back `SpreadPlan`s, which `services/binder.py` turns into placements.

Two deliberate departures from the spec's formula, both visible in `ScoreBreakdown`:

* **Unmeasurable terms are excluded, not guessed.** Colour coherence needs `dominant_color_lab`,
  which is null until `bb binder extract-colors` has run, and hero centrality needs a template
  with a hero slot. Scoring a missing term as 0 would punish a layout for a gap in the data, and
  scoring it as 1 would flatter it. Measured terms are re-normalised over their own weights, and
  the breakdown says which ones counted.
* **The orphan penalty is a layout-level term**, so `score_layout` scores a whole sequence of
  spreads rather than one. A group split across non-adjacent spreads is the thing being penalised,
  and that is invisible from inside a single spread.
"""
from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.binder.color import delta_e2000
from app.binder.layout import PlacementSpec
from app.binder.templates import SpreadTemplate, pick_template

# What counts as "very different" for the colour term. CIEDE2000 is built so ~1.0 is a just-
# noticeable difference; 40 is comfortably "unrelated colours", so a spread averaging that scores
# zero coherence rather than something negative.
DE_NORM = 40.0

MIN_GROUP = 4
MAX_GROUP = 14


class ClusterKey(StrEnum):
    """What makes cards belong together, per docs/05-binder-spec.md."""

    SPECIES = "species"
    ARTIST = "artist"
    COLOUR = "colour"
    EVOLUTION = "evolution"


@dataclass(slots=True)
class MichiCard:
    """One candidate card, independent of the ORM."""

    card_variant_id: int
    card_id: int
    name: str
    number_sort: int = 0
    rarity: str | None = None
    artist: str | None = None
    pokedex_number: int | None = None
    lab: tuple[float, float, float] | None = None
    market_value: float | None = None
    is_hero: bool = False

    @property
    def hue_angle(self) -> float:
        """Hue in degrees, for ordering a spread's cards around the colour wheel. Neutral cards
        sort last rather than landing arbitrarily at 0 degrees (red)."""
        if self.lab is None:
            return 999.0
        return math.degrees(math.atan2(self.lab[2], self.lab[1])) % 360.0


@dataclass(slots=True)
class ScoreWeights:
    """Defaults from docs/05-binder-spec.md. Exposed to the user, which is the point -- these
    encode taste, and one collector's balanced spread is another's cluttered one."""

    symmetry: float = 0.30
    colour: float = 0.25
    hero: float = 0.20
    fill: float = 0.15
    orphan: float = 0.10


@dataclass(slots=True)
class ScoreBreakdown:
    """Every term, so a recommendation can be explained rather than asserted."""

    total: float
    symmetry: float | None
    colour: float | None
    hero: float | None
    fill: float | None
    orphan: float
    measured: tuple[str, ...] = ()
    unmeasured: tuple[str, ...] = ()


@dataclass(slots=True)
class SpreadPlan:
    """One facing pair: which template, and what sits in each card slot."""

    spread_index: int
    template: SpreadTemplate
    group_key: str
    # Parallel to `template.card_slots_in_reading_order()`; a None means that slot stayed empty.
    cards: list[MichiCard | None] = field(default_factory=list)

    def placed_cards(self) -> list[MichiCard]:
        return [c for c in self.cards if c is not None]


# --- 1. clustering ------------------------------------------------------------------------------


def _group_value(card: MichiCard, key: ClusterKey) -> str | None:
    if key is ClusterKey.SPECIES or key is ClusterKey.EVOLUTION:
        return str(card.pokedex_number) if card.pokedex_number is not None else None
    if key is ClusterKey.ARTIST:
        return card.artist
    # Colour: bucket by hue so "the red page" is a real group rather than one card per shade.
    if card.lab is None:
        return None
    return f"hue{int(card.hue_angle // 30) * 30:03d}"


def cluster_pool(
    cards: Sequence[MichiCard],
    key: ClusterKey,
    *,
    min_size: int = MIN_GROUP,
    max_size: int = MAX_GROUP,
) -> list[list[MichiCard]]:
    """Groups of `min_size`..`max_size` cards, per the spec's step 1.

    Cards the key cannot place -- no artist recorded, no colour extracted yet -- are not dropped.
    They are pooled into "misc" groups at the end, because a binder plan that silently omits cards
    you own is the same failure the not-owned badge exists to prevent, in reverse.

    Groups larger than `max_size` are split into consecutive chunks; the allocation step keeps
    those chunks on adjacent spreads so they do not take the orphan penalty.
    """
    buckets: dict[str, list[MichiCard]] = {}
    unkeyed: list[MichiCard] = []
    for card in cards:
        value = _group_value(card, key)
        if value is None:
            unkeyed.append(card)
        else:
            buckets.setdefault(value, []).append(card)

    # Evolution lines read by pokedex number; everything else by hue then card number, which is
    # what makes a colour-themed page progress rather than jump around.
    def order(group: list[MichiCard]) -> list[MichiCard]:
        if key is ClusterKey.EVOLUTION:
            return sorted(group, key=lambda c: (c.pokedex_number or 0, c.number_sort))
        return sorted(group, key=lambda c: (c.hue_angle, c.number_sort))

    groups: list[list[MichiCard]] = []
    leftovers: list[MichiCard] = []
    for value in sorted(buckets):
        group = order(buckets[value])
        if len(group) < min_size:
            leftovers.extend(group)
            continue
        groups.extend(_even_chunks(group, max_size))

    leftovers.extend(unkeyed)
    groups.extend(_even_chunks(order(leftovers), max_size))
    return groups


def _even_chunks(items: list[MichiCard], max_size: int) -> list[list[MichiCard]]:
    """Split into the fewest chunks that all fit, balanced.

    Slicing at `max_size` leaves a trailing sliver -- 30 cards become 14, 14, 2 -- and an earlier
    version merged that sliver back into the previous chunk, which pushed it over the limit and
    past what any template could hold. Splitting evenly (10, 10, 10) avoids both.
    """
    if not items:
        return []
    n = -(-len(items) // max_size)  # ceil
    size, extra = divmod(len(items), n)
    chunks: list[list[MichiCard]] = []
    start = 0
    for i in range(n):
        end = start + size + (1 if i < extra else 0)
        chunks.append(items[start:end])
        start = end
    return chunks


# --- 2-4. allocation, template choice, assignment -----------------------------------------------


def _hero_of(group: Sequence[MichiCard]) -> MichiCard | None:
    """The card the spread is built around: a user flag wins, else the most valuable."""
    flagged = [c for c in group if c.is_hero]
    if flagged:
        return flagged[0]
    priced = [c for c in group if c.market_value is not None]
    if priced:
        return max(priced, key=lambda c: (c.market_value or 0.0, -c.number_sort))
    return group[0] if group else None


def assign_group(
    group: Sequence[MichiCard],
    template: SpreadTemplate,
    spread_index: int,
    group_key: str,
    *,
    rng: random.Random | None = None,
    shuffle: bool = False,
) -> SpreadPlan:
    """Put a group's cards into a template's slots (spec step 4).

    The hero goes to the hero slot; the rest keep the group's existing order, which clustering
    already sorted by hue (or pokedex number for evolution lines). `shuffle` perturbs the
    non-hero order for one trial of the best-of-N search.
    """
    slots = template.card_slots_in_reading_order()
    hero = _hero_of(group)
    rest = [c for c in group if c is not hero]
    if shuffle and rng is not None:
        rest = rest[:]
        rng.shuffle(rest)

    ordered: list[MichiCard] = ([hero] if hero is not None else []) + rest
    # If the template has no hero slot the hero is just another card, and leads the reading order.
    cards: list[MichiCard | None] = []
    queue = list(ordered)
    for _ in slots:
        cards.append(queue.pop(0) if queue else None)
    return SpreadPlan(spread_index, template, group_key, cards)


# --- 5. scoring ---------------------------------------------------------------------------------


def _occupancy(plan: SpreadPlan) -> dict[tuple[int, int], str]:
    """Grid cell -> "card" | "insert" | "empty", expanded over spans."""
    grid: dict[tuple[int, int], str] = {}
    t = plan.template
    for r in range(t.rows):
        for c in range(2 * t.cols):
            grid[(r, c)] = "empty"

    card_slots = t.card_slots_in_reading_order()
    filled_slots = {
        id(slot) for slot, card in zip(card_slots, plan.cards, strict=False) if card is not None
    }
    for slot in t.slots:
        if slot.kind == "insert":
            kind = "insert"
        elif slot.holds_card:
            kind = "card" if id(slot) in filled_slots else "empty"
        else:
            kind = "empty"
        for r in range(slot.row, slot.row + slot.row_span):
            for c in range(slot.col, slot.col + slot.col_span):
                grid[(r, c)] = kind
    return grid


def symmetry_score(plan: SpreadPlan) -> float:
    """Fraction of cells whose mirror across the spread's vertical axis holds the same kind.

    A perfectly mirrored spread scores 1.0 -- which is what makes this term testable against a
    hand-built layout with a known-correct value.
    """
    grid = _occupancy(plan)
    t = plan.template
    width = 2 * t.cols
    matches = 0
    for (r, c), kind in grid.items():
        if grid.get((r, width - 1 - c)) == kind:
            matches += 1
    return matches / len(grid) if grid else 0.0


def colour_coherence(plan: SpreadPlan) -> float | None:
    """1 - mean CIEDE2000 between orthogonally adjacent cards, normalised by DE_NORM.

    None when fewer than one adjacent pair has colour data, which is the state of the whole
    catalogue until `bb binder extract-colors` has run.
    """
    grid_cards: dict[tuple[int, int], MichiCard] = {}
    for slot, card in zip(
        plan.template.card_slots_in_reading_order(), plan.cards, strict=False
    ):
        if card is not None:
            grid_cards[(slot.row, slot.col)] = card

    deltas: list[float] = []
    for (r, c), card in grid_cards.items():
        if card.lab is None:
            continue
        for dr, dc in ((0, 1), (1, 0)):
            other = grid_cards.get((r + dr, c + dc))
            if other is not None and other.lab is not None:
                deltas.append(delta_e2000(card.lab, other.lab))
    if not deltas:
        return None
    mean = sum(deltas) / len(deltas)
    return max(0.0, 1.0 - min(mean / DE_NORM, 1.0))


def hero_centrality(plan: SpreadPlan) -> float | None:
    """1 at the spread's centre, 0 at its furthest corner. None if the template has no hero."""
    t = plan.template
    hero_slot = t.hero
    if hero_slot is None:
        return None
    slots = t.card_slots_in_reading_order()
    if not slots or slots[0] is not hero_slot or not plan.cards or plan.cards[0] is None:
        return None

    centre_r, centre_c = (t.rows - 1) / 2, (2 * t.cols - 1) / 2
    # Centre of the slot itself, so a 2x2 hero is measured from its middle.
    hero_r = hero_slot.row + (hero_slot.row_span - 1) / 2
    hero_c = hero_slot.col + (hero_slot.col_span - 1) / 2
    distance = math.hypot(hero_r - centre_r, hero_c - centre_c)
    max_distance = math.hypot(centre_r, centre_c)
    return 1.0 - min(distance / max_distance, 1.0) if max_distance > 0 else 1.0


def fill_balance(plan: SpreadPlan) -> float:
    """1 when empty pockets are spread evenly across the two pages, 0 when all on one side."""
    grid = _occupancy(plan)
    cols = plan.template.cols
    left = sum(1 for (_, c), kind in grid.items() if kind == "empty" and c < cols)
    right = sum(1 for (_, c), kind in grid.items() if kind == "empty" and c >= cols)
    total = left + right
    if total == 0:
        return 1.0
    return 1.0 - abs(left - right) / total


def orphan_penalty(plans: Sequence[SpreadPlan]) -> float:
    """Fraction of groups landing on non-adjacent spreads.

    A group split over spreads 2 and 5 is the thing the spec calls an orphan: you turn the page
    and the theme has gone. Split over 2 and 3 it is simply a long section, and costs nothing.
    """
    if not plans:
        return 0.0
    by_group: dict[str, list[int]] = {}
    for plan in plans:
        by_group.setdefault(plan.group_key, []).append(plan.spread_index)
    orphaned = 0
    for indices in by_group.values():
        span = max(indices) - min(indices) + 1
        if span != len(set(indices)):
            orphaned += 1
    return orphaned / len(by_group)


def score_layout(
    plans: Sequence[SpreadPlan], weights: ScoreWeights | None = None
) -> ScoreBreakdown:
    """The spec's weighted score over a whole sequence of spreads."""
    w = weights or ScoreWeights()
    if not plans:
        return ScoreBreakdown(
            0.0, None, None, None, None, 0.0, (), ("symmetry", "colour", "hero", "fill")
        )

    sym = sum(symmetry_score(p) for p in plans) / len(plans)
    fill = sum(fill_balance(p) for p in plans) / len(plans)

    colours = [v for v in (colour_coherence(p) for p in plans) if v is not None]
    colour = sum(colours) / len(colours) if colours else None
    heroes = [v for v in (hero_centrality(p) for p in plans) if v is not None]
    hero = sum(heroes) / len(heroes) if heroes else None

    orphan = orphan_penalty(plans)

    terms = [("symmetry", w.symmetry, sym), ("fill", w.fill, fill),
             ("colour", w.colour, colour), ("hero", w.hero, hero)]
    measured = [(n, wt, v) for n, wt, v in terms if v is not None]
    unmeasured = tuple(n for n, _, v in terms if v is None)

    weight_sum = sum(wt for _, wt, _ in measured)
    base = sum(wt * v for _, wt, v in measured) / weight_sum if weight_sum else 0.0
    total = base - w.orphan * orphan
    return ScoreBreakdown(
        total=total,
        symmetry=sym,
        colour=colour,
        hero=hero,
        fill=fill,
        orphan=orphan,
        measured=tuple(n for n, _, _ in measured),
        unmeasured=unmeasured,
    )


# --- the whole pipeline -------------------------------------------------------------------------


@dataclass(slots=True)
class MichiResult:
    plans: list[SpreadPlan]
    score: ScoreBreakdown
    trials: int
    groups: int
    placed: int
    unplaced: int


def auto_layout_michi(
    cards: Sequence[MichiCard],
    templates: Sequence[SpreadTemplate],
    *,
    rows: int = 3,
    cols: int = 3,
    pages: int = 20,
    is_side_loading: bool = True,
    cluster_key: ClusterKey = ClusterKey.SPECIES,
    weights: ScoreWeights | None = None,
    trials: int = 24,
    seed: int = 0,
) -> MichiResult:
    """Cluster, allocate, template, assign, score -- best of `trials`.

    Seeded, so the same pool and seed give the same binder. An auto-layout that shuffled every
    time you looked at it would be impossible to reason about, and undo already exists for
    deliberate change.
    """
    usable = [t for t in templates if t.rows == rows and t.cols == cols]
    usable = [t for t in usable if is_side_loading or not t.requires_side_loading]
    if not usable:
        raise ValueError(
            f"No {rows}x{cols} templates available"
            + ("" if is_side_loading else " for a top-loading binder")
            + " -- add one to data/binder_templates/."
        )

    groups = cluster_pool(cards, cluster_key)
    max_spreads = max(1, pages // 2)
    groups = groups[:max_spreads]

    best: tuple[float, list[SpreadPlan], ScoreBreakdown] | None = None
    for trial in range(max(1, trials)):
        rng = random.Random(seed + trial)
        plans: list[SpreadPlan] = []
        for spread_index, group in enumerate(groups):
            template = pick_template(usable, len(group), is_side_loading=is_side_loading)
            if template is None:
                continue
            plans.append(
                assign_group(
                    group,
                    template,
                    spread_index,
                    group_key=f"g{spread_index}",
                    rng=rng,
                    shuffle=trial > 0,
                )
            )
        breakdown = score_layout(plans, weights)
        if best is None or breakdown.total > best[0]:
            best = (breakdown.total, plans, breakdown)

    assert best is not None
    _, plans, breakdown = best
    actually_placed = sum(len(p.placed_cards()) for p in plans)
    return MichiResult(
        plans=plans,
        score=breakdown,
        trials=max(1, trials),
        groups=len(groups),
        placed=actually_placed,
        unplaced=len(cards) - actually_placed,
    )


def plans_to_placements(plans: Iterable[SpreadPlan]) -> list[PlacementSpec]:
    """Turn scored spreads into the placements the service layer persists.

    Follows the storage convention in `layout.py`: a gutter-spanning slot is stored on the even
    (left) page with its `col` left in spread coordinates; everything else converts back to a
    per-page column.
    """
    specs: list[PlacementSpec] = []
    for plan in plans:
        left_page = plan.spread_index * 2
        template = plan.template
        card_slots = template.card_slots_in_reading_order()
        by_slot = {
            id(slot): card
            for slot, card in zip(card_slots, plan.cards, strict=False)
            if card is not None
        }
        for slot in template.slots:
            if slot.kind == "empty":
                continue
            card = by_slot.get(id(slot))
            if slot.holds_card and card is None:
                continue
            if slot.spans_gutter:
                page_index, col = left_page, slot.col
            else:
                page_index = left_page + (1 if slot.col >= template.cols else 0)
                col = slot.col - (template.cols if slot.col >= template.cols else 0)
            specs.append(
                PlacementSpec(
                    page_index=page_index,
                    row=slot.row,
                    col=col,
                    kind="card" if slot.holds_card else "insert",
                    row_span=slot.row_span,
                    col_span=slot.col_span,
                    card_variant_id=card.card_variant_id if card else None,
                    spans_gutter=slot.spans_gutter,
                )
            )
    # Insert slots have no asset yet; the designer fills them in. They would fail the service's
    # "kind=insert requires an insert_asset_id" invariant, so they are dropped here and the
    # template's card slots are what actually get written.
    return [s for s in specs if s.kind == "card"]
