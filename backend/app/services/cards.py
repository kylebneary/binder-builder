"""Card search across the whole catalogue, and the facet values that drive its filter UI.

One query builder serves three callers: the search page (card-level, paginated), filter goals
(variant ids, materialised into goal_item), and the binder pool (a goal's cards). Keeping them on
one builder is what guarantees a "live filter" goal holds exactly the cards the search showed.

Matching is variant-level -- a variant is the unit a goal holds and a binder pocket places (see
docs/02-data-model.md) -- and results are grouped back up to cards for display. Plain dataclasses
in/out, per the layer rules in docs/01-architecture.md.
"""
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Integer, Numeric, Select, String, cast, column, func, or_, select, table
from sqlalchemy.orm import Session

from app.ingest.printing_tags import printing_label
from app.models import Card, CardVariant, CollectionItem, GoalItem, Set
from app.services.prices import get_current_prices
from app.services.sets import VariantView

OwnedFilter = Literal["owned", "missing"]
VariantScope = Literal["canonical", "all"]
SortKey = Literal["newest", "oldest", "name", "price"]

# The `current_price` view, declared for use inside ORM-built queries. `market` is typed so
# Decimal bounds bind correctly -- SQLite's driver rejects a raw Decimal parameter.
_current_price = table(
    "current_price",
    column("tcgplayer_product_id", Integer),
    column("sub_type_name", String),
    column("market", Numeric(10, 2)),
)

# Older filter goals were written with singular keys before the search builder existed. Read
# them, never write them.
_LEGACY_KEYS = {
    "set_id": "set_ids",
    "rarity": "rarities",
    "artist": "artists",
    "supertype": "supertypes",
}


@dataclass(slots=True)
class CardQuery:
    """Every filter the search understands. Empty lists and None mean "no constraint", and
    constraints combine with AND; values within one list combine with OR."""

    q: str | None = None  # case-insensitive substring of the card name
    set_ids: list[int] = field(default_factory=list)
    series: list[str] = field(default_factory=list)
    rarities: list[str] = field(default_factory=list)
    supertypes: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)  # energy types, e.g. "Fire"
    subtypes: list[str] = field(default_factory=list)  # "ex", "VMAX", "Supporter", ...
    artists: list[str] = field(default_factory=list)
    pokedex_numbers: list[int] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    # "canonical" is one printing per card, the "owned" definition used everywhere else;
    # "all" is the master-set treatment, every printing separately.
    variant_scope: VariantScope = "canonical"
    owned: OwnedFilter | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    year_from: int | None = None
    year_to: int | None = None
    goal_id: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CardQuery":
        known = {f.name for f in fields(cls)}
        clean: dict[str, Any] = {}
        for key, value in (data or {}).items():
            key = _LEGACY_KEYS.get(key, key)
            if key not in known or value is None:
                continue
            if isinstance(getattr(_EMPTY_QUERY, key), list) and not isinstance(value, list):
                value = [value]
            if key in ("min_price", "max_price"):
                value = Decimal(str(value))
            clean[key] = value
        return cls(**clean)

    def to_goal_filter(self) -> dict[str, Any]:
        """The query as a filter goal stores it in `goal.filter_json`.

        `owned` and `goal_id` are dropped: a goal whose membership depends on what you own would
        shrink every time you bought a card, so it could never show progress. The need list is
        already where ownership is accounted for.
        """
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if key in ("owned", "goal_id") or value is None or value == []:
                continue
            if key == "variant_scope" and value == "canonical":
                continue
            out[key] = str(value) if isinstance(value, Decimal) else value
        return out

    def describes_anything(self) -> bool:
        """True when at least one card-narrowing filter is set. A filter goal over the whole
        catalogue is almost certainly a mistake, so callers refuse it."""
        return bool(self.to_goal_filter().keys() - {"variant_scope"})


_EMPTY_QUERY = CardQuery()


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _json_list_contains(col: Any, value: str | int) -> Any:
    """Portable "this JSON list contains this element" for `types`, `subtypes` and
    `national_pokedex_numbers`.

    SQLite has json_each and Postgres has @>, but no one spelling works on both, and CLAUDE.md
    rules out engine-specific SQL. These columns are always written as json.dumps output
    (`["Fire", "Water"]`, `[243, 244]`) and Postgres' JSON type keeps the text verbatim, so an
    element is its JSON token bounded by `[` or `, ` on the left and `,` or `]` on the right.
    The boundaries are what stop dex 25 matching 125 or 250.
    """
    token = _like_escape(json.dumps(value))
    text_col = cast(col, String)
    patterns = (f"%[{token}]%", f"%[{token},%", f"% {token},%", f"% {token}]%")
    return or_(*(text_col.like(p, escape="\\") for p in patterns))


def _apply_card_filters(stmt: Select, query: CardQuery) -> Select:
    """The card- and set-level constraints. `stmt` must already join Card and Set."""
    if query.q and query.q.strip():
        needle = _like_escape(query.q.strip().lower())
        stmt = stmt.where(func.lower(Card.name).like(f"%{needle}%", escape="\\"))
    if query.set_ids:
        stmt = stmt.where(Card.set_id.in_(query.set_ids))
    if query.series:
        stmt = stmt.where(Set.series.in_(query.series))
    if query.rarities:
        stmt = stmt.where(Card.rarity.in_(query.rarities))
    if query.supertypes:
        stmt = stmt.where(Card.supertype.in_(query.supertypes))
    if query.artists:
        stmt = stmt.where(Card.artist.in_(query.artists))
    if query.types:
        stmt = stmt.where(or_(*(_json_list_contains(Card.types, t) for t in query.types)))
    if query.subtypes:
        stmt = stmt.where(or_(*(_json_list_contains(Card.subtypes, s) for s in query.subtypes)))
    if query.pokedex_numbers:
        dex = Card.national_pokedex_numbers
        stmt = stmt.where(or_(*(_json_list_contains(dex, n) for n in query.pokedex_numbers)))
    if query.year_from is not None:
        stmt = stmt.where(Set.release_date >= date(query.year_from, 1, 1))
    if query.year_to is not None:
        stmt = stmt.where(Set.release_date <= date(query.year_to, 12, 31))
    return stmt


def _needs_price(query: CardQuery, sort: SortKey | None = None) -> bool:
    return query.min_price is not None or query.max_price is not None or sort == "price"


def _variant_stmt(
    query: CardQuery, collection_id: int | None, *, with_price: bool = False
) -> Select:
    """One row per matching variant: (variant_id, card_id[, market])."""
    columns: list[Any] = [CardVariant.id.label("variant_id"), Card.id.label("card_id")]
    price = None
    if with_price:
        # Aggregated first: the view can hold one row per source for the same day, and a plain
        # join would then duplicate variants.
        price = (
            select(
                _current_price.c.tcgplayer_product_id,
                _current_price.c.sub_type_name,
                func.max(_current_price.c.market).label("market"),
            )
            .group_by(_current_price.c.tcgplayer_product_id, _current_price.c.sub_type_name)
            .subquery()
        )
        columns.append(price.c.market.label("market"))

    stmt = (
        select(*columns)
        .select_from(CardVariant)
        .join(Card, CardVariant.card_id == Card.id)
        .join(Set, Card.set_id == Set.id)
    )
    if price is not None:
        stmt = stmt.outerjoin(
            price,
            (price.c.tcgplayer_product_id == CardVariant.tcgplayer_product_id)
            & (price.c.sub_type_name == CardVariant.tcgplayer_sub_type_name),
        )
        if query.min_price is not None:
            stmt = stmt.where(price.c.market >= query.min_price)
        if query.max_price is not None:
            stmt = stmt.where(price.c.market <= query.max_price)

    stmt = _apply_card_filters(stmt, query)

    # A goal's own variants are exactly what it wants, so scope only applies to open searches.
    if query.goal_id is not None:
        stmt = stmt.where(
            CardVariant.id.in_(
                select(GoalItem.card_variant_id).where(GoalItem.goal_id == query.goal_id)
            )
        )
    elif query.variant_scope == "canonical":
        stmt = stmt.where(CardVariant.is_canonical.is_(True))

    if query.variants:
        stmt = stmt.where(CardVariant.variant.in_(query.variants))

    if query.owned is not None:
        if collection_id is None:
            raise ValueError("Filtering on ownership needs a collection")
        owned = (
            select(CollectionItem.id)
            .where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.card_variant_id == CardVariant.id,
                CollectionItem.quantity > 0,
            )
            .exists()
        )
        stmt = stmt.where(owned if query.owned == "owned" else ~owned)
    return stmt


def variant_ids(
    db: Session, query: CardQuery, *, collection_id: int | None = None
) -> list[int]:
    """Every variant matching the query, in set-release then card-number order."""
    sub = _variant_stmt(query, collection_id, with_price=_needs_price(query)).subquery()
    rows = db.execute(
        select(sub.c.variant_id)
        .join(Card, Card.id == sub.c.card_id)
        .join(Set, Set.id == Card.set_id)
        .distinct()
        .order_by(*_SORTS["oldest"](sub), sub.c.variant_id)
    ).all()
    # DISTINCT with ORDER BY on non-selected columns can still repeat an id on some engines.
    seen: dict[int, None] = {}
    for (variant_id,) in rows:
        seen.setdefault(variant_id, None)
    return list(seen)


@dataclass(slots=True)
class CardSearchItem:
    id: int
    ptcg_card_id: str
    number: str
    number_sort: int
    name: str
    supertype: str | None
    rarity: str | None
    artist: str | None
    types: list[str]
    subtypes: list[str]
    national_pokedex_numbers: list[int]
    image_small: str | None
    image_large: str | None
    set_id: int
    ptcg_set_id: str
    set_name: str
    series: str | None
    release_date: date | None
    # Only the variants that matched, so a "Poke Ball holo" search does not offer the Normal.
    variants: list[VariantView] = field(default_factory=list)

    @property
    def is_owned(self) -> bool:
        """Owned if any listed variant is held. Mirrors CardView.is_owned, except that it
        cannot insist on the canonical variant: a goal pool may list only a reverse holo."""
        return any(v.owned_quantity > 0 for v in self.variants)


@dataclass(slots=True)
class CardSearchResult:
    total: int
    offset: int
    limit: int
    cards: list[CardSearchItem] = field(default_factory=list)
    # Cards that match the card-level filters but own no `card_variant` row, so they cannot go in
    # a goal or a binder. Variants come from the price feed; this is mostly unpriced chase cards.
    # Counted, not silently omitted -- the same reason auto-layout reports `skipped_no_variant`.
    unplaceable_count: int = 0


_SORTS: dict[str, Any] = {
    "newest": lambda sub: (
        Set.release_date.desc().nulls_last(), Set.id.desc(), Card.number_sort, Card.number
    ),
    "oldest": lambda sub: (
        Set.release_date.asc().nulls_last(), Set.id, Card.number_sort, Card.number
    ),
    "name": lambda sub: (Card.name, Set.release_date.asc().nulls_last(), Card.number_sort),
    "price": lambda sub: (sub.c.price.desc().nulls_last(), Card.name),
}


def search_cards(
    db: Session,
    query: CardQuery,
    *,
    collection_id: int,
    sort: SortKey = "newest",
    offset: int = 0,
    limit: int = 60,
) -> CardSearchResult:
    with_price = _needs_price(query, sort)
    matches = _variant_stmt(query, collection_id, with_price=with_price).subquery()

    per_card_cols: list[Any] = [matches.c.card_id]
    if with_price:
        per_card_cols.append(func.max(matches.c.market).label("price"))
    per_card = select(*per_card_cols).group_by(matches.c.card_id).subquery()

    total = db.execute(select(func.count()).select_from(per_card)).scalar_one()

    page_ids = [
        row[0]
        for row in db.execute(
            select(per_card.c.card_id)
            .join(Card, Card.id == per_card.c.card_id)
            .join(Set, Set.id == Card.set_id)
            .order_by(*_SORTS[sort](per_card))
            .offset(offset)
            .limit(limit)
        ).all()
    ]

    cards = _load_cards(db, query, page_ids, collection_id) if page_ids else []
    return CardSearchResult(
        total=total,
        offset=offset,
        limit=limit,
        cards=cards,
        unplaceable_count=_unplaceable_count(db, query),
    )


def _unplaceable_count(db: Session, query: CardQuery) -> int:
    """Only meaningful when the query could have matched a variant-less card at all: a goal
    holds variants by definition, and variant, price and owned filters need a variant to test.
    "missing" still counts -- a card with no variant is certainly not owned."""
    if (
        query.goal_id is not None
        or query.variants
        or query.owned == "owned"
        or query.min_price is not None
        or query.max_price is not None
    ):
        return 0
    stmt = (
        select(func.count(Card.id))
        .select_from(Card)
        .join(Set, Card.set_id == Set.id)
        .where(~select(CardVariant.id).where(CardVariant.card_id == Card.id).exists())
    )
    return db.execute(_apply_card_filters(stmt, query)).scalar_one() or 0


def _load_cards(
    db: Session, query: CardQuery, card_ids: list[int], collection_id: int
) -> list[CardSearchItem]:
    """Hydrate one page of card ids, keeping their order and only their matching variants."""
    matching = _variant_stmt(query, collection_id, with_price=_needs_price(query)).where(
        Card.id.in_(card_ids)
    ).subquery()
    rows = db.execute(
        select(CardVariant, Card, Set)
        .join(Card, CardVariant.card_id == Card.id)
        .join(Set, Card.set_id == Set.id)
        .where(CardVariant.id.in_(select(matching.c.variant_id)))
        .order_by(CardVariant.is_canonical.desc(), CardVariant.id)
    ).all()

    product_ids = sorted({v.tcgplayer_product_id for v, _, _ in rows if v.tcgplayer_product_id})
    prices = get_current_prices(db, product_ids)
    owned_by_variant: dict[int, int] = defaultdict(int)
    held = db.execute(
        select(CollectionItem.card_variant_id, CollectionItem.quantity).where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.card_variant_id.in_([v.id for v, _, _ in rows]),
        )
    ).all()
    for variant_id, qty in held:
        owned_by_variant[variant_id] += qty

    by_card: dict[int, CardSearchItem] = {}
    for variant, card, set_row in rows:
        item = by_card.get(card.id)
        if item is None:
            item = by_card[card.id] = CardSearchItem(
                id=card.id,
                ptcg_card_id=card.ptcg_card_id,
                number=card.number,
                number_sort=card.number_sort,
                name=card.name,
                supertype=card.supertype,
                rarity=card.rarity,
                artist=card.artist,
                types=list(card.types or []),
                subtypes=list(card.subtypes or []),
                national_pokedex_numbers=list(card.national_pokedex_numbers or []),
                image_small=card.image_small,
                image_large=card.image_large,
                set_id=set_row.id,
                ptcg_set_id=set_row.ptcg_set_id,
                set_name=set_row.name,
                series=set_row.series,
                release_date=set_row.release_date,
            )
        price = None
        if variant.tcgplayer_product_id is not None and variant.tcgplayer_sub_type_name is not None:
            price = prices.get((variant.tcgplayer_product_id, variant.tcgplayer_sub_type_name))
        item.variants.append(
            VariantView(
                id=variant.id,
                variant=str(variant.variant),
                tcgplayer_product_id=variant.tcgplayer_product_id,
                tcgplayer_sub_type_name=variant.tcgplayer_sub_type_name,
                is_canonical=variant.is_canonical,
                market_price=price["market"] if price else None,
                owned_quantity=owned_by_variant.get(variant.id, 0),
                is_special=variant.is_special,
                label=printing_label(str(variant.variant)),
            )
        )
    return [by_card[cid] for cid in card_ids if cid in by_card]


# --- facets ---------------------------------------------------------------------------------


@dataclass(slots=True)
class FacetValue:
    value: str
    count: int
    label: str | None = None  # printings only: the tagged printing's collector-facing name


@dataclass(slots=True)
class SpeciesFacet:
    pokedex_number: int
    name: str
    count: int


@dataclass(slots=True)
class CardFacets:
    rarities: list[FacetValue] = field(default_factory=list)
    supertypes: list[FacetValue] = field(default_factory=list)
    types: list[FacetValue] = field(default_factory=list)
    subtypes: list[FacetValue] = field(default_factory=list)
    artists: list[FacetValue] = field(default_factory=list)
    series: list[FacetValue] = field(default_factory=list)
    variants: list[FacetValue] = field(default_factory=list)
    species: list[SpeciesFacet] = field(default_factory=list)


def _ranked(counter: Counter[str]) -> list[FacetValue]:
    return [FacetValue(v, n) for v, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))]


def _alphabetical(counter: Counter[str]) -> list[FacetValue]:
    return [FacetValue(v, n) for v, n in sorted(counter.items(), key=lambda kv: kv[0].lower())]


def species_name(names: Counter[str]) -> str:
    """The species name for a dex number, from the names of the cards filed under it alone.

    The catalogue has no species table, so this picks the shortest card name and breaks ties by
    frequency: dex 25 is printed as "Pikachu", "Pikachu ex", "Ash's Pikachu" and "Pikachu V",
    and only the bare species name is a prefix-free shortest. A heuristic, but every value it
    produces is a real card name from the catalogue rather than a guess.
    """
    return min(names.items(), key=lambda kv: (len(kv[0]), -kv[1], kv[0]))[0]


def card_facets(db: Session) -> CardFacets:
    """Every distinct filter value in the catalogue, with card counts, for the search UI."""
    rows = db.execute(
        select(
            Card.supertype,
            Card.rarity,
            Card.artist,
            Card.types,
            Card.subtypes,
            Card.national_pokedex_numbers,
            Card.name,
        )
    ).all()

    rarities: Counter[str] = Counter()
    supertypes: Counter[str] = Counter()
    artists: Counter[str] = Counter()
    types: Counter[str] = Counter()
    subtypes: Counter[str] = Counter()
    dex_counts: Counter[int] = Counter()
    dex_names: dict[int, Counter[str]] = defaultdict(Counter)
    for supertype, rarity, artist, card_types, card_subtypes, dex, name in rows:
        if supertype:
            supertypes[supertype] += 1
        if rarity:
            rarities[rarity] += 1
        if artist:
            artists[artist] += 1
        types.update(card_types or [])
        subtypes.update(card_subtypes or [])
        for number in dex or []:
            dex_counts[number] += 1
        # Names are learned only from single-species cards, so "Pikachu & Zekrom-GX" cannot
        # become the name of either.
        if dex and len(dex) == 1:
            dex_names[dex[0]][name] += 1

    series: Counter[str] = Counter()
    for set_series, count in db.execute(
        select(Set.series, func.count(Card.id))
        .join(Card, Card.set_id == Set.id)
        .group_by(Set.series)
    ).all():
        if set_series:
            series[set_series] = count

    variants: Counter[str] = Counter()
    for variant, count in db.execute(
        select(CardVariant.variant, func.count(CardVariant.id)).group_by(CardVariant.variant)
    ).all():
        variants[str(variant)] = count

    species = [
        SpeciesFacet(number, species_name(dex_names[number]), dex_counts[number])
        for number in sorted(dex_counts)
        if dex_names.get(number)
    ]

    printings = _ranked(variants)
    for facet in printings:
        facet.label = printing_label(facet.value)

    return CardFacets(
        rarities=_ranked(rarities),
        supertypes=_ranked(supertypes),
        types=_ranked(types),
        subtypes=_ranked(subtypes),
        artists=_alphabetical(artists),
        series=_ranked(series),
        variants=printings,
        species=species,
    )
