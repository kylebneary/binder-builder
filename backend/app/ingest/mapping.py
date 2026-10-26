"""Joining pokemontcg.io cards to TCGplayer product IDs.

There is no shared key. This is the hardest correctness problem in Phase 1 -- see
docs/06-roadmap.md "Where the hard parts are". Unmatched rows go to a review queue.
They must never fail silently, because a silent mismatch yields confidently wrong prices.
"""
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ingest.printing_tags import Printing


@dataclass(slots=True)
class MatchResult:
    ptcg_card_id: str
    tcgplayer_product_id: int | None
    confidence: float
    reason: str


def normalize_number(raw: str | None) -> str | None:
    """'021/128' -> '21'; 'TG12/TG30' -> 'TG12'; '025a' -> '25A'."""
    if not raw:
        return None
    head = raw.split("/")[0].strip().upper()
    m = re.match(r"^([A-Z]*)0*(\d+)([A-Z]*)$", head)
    if not m:
        return head
    prefix, digits, suffix = m.groups()
    return f"{prefix}{int(digits)}{suffix}"


def normalize_name(raw: str) -> str:
    """Strip punctuation and variant suffixes for comparison."""
    s = raw.lower()
    # TCGplayer appends the rarity/treatment in parentheses; pokemontcg.io does not.
    s = re.sub(r"\s*\([^)]*\)", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_disambiguating_number(clean_name: str, card_number: str | None) -> str:
    """Undo tcgcsv's habit of appending a card's own number to `cleanName` to disambiguate two
    cards that share a name (e.g. a secret rare reprinting a regular card's name): tcgcsv's
    already-sanitized `cleanName` turns 'Alolan Dugtrio - 123/191' into 'Alolan Dugtrio 123 191'
    (punctuation gone, digits left as trailing tokens). pokemontcg.io's name for both is just
    'Alolan Dugtrio'. The card number is matched separately (see match_cards_in_set) so this
    strips exactly the token pair tcgcsv derived from `card_number`, rather than guessing at a
    generic trailing-digits pattern that could clip a Pokemon name that legitimately ends in a
    number (e.g. 'Porygon2', which has no separating space so is unaffected here).
    """
    if not card_number:
        return clean_name
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", card_number) if t]
    if not tokens:
        return clean_name
    suffix = " " + " ".join(tokens)
    if clean_name.endswith(suffix):
        return clean_name[: -len(suffix)]
    return clean_name


_KNOWN_TREATMENT_SUFFIXES = (
    "full art",
    "alternate full art",
    "rainbow rare",
    "rainbow",
    "secret rare",
    "alternate art secret",
    "secret",
    "gold rare",
    "gold",
    "alternate art",
    "alt art",
)


def strip_known_treatment_suffix(clean_name: str) -> str:
    """Undo tcgcsv's habit of appending a card's special-treatment name (e.g. 'Full Art',
    'Rainbow Rare') to `cleanName` to disambiguate it from a regular-print card sharing the same
    base name in the same set -- pokemontcg.io's name for the special-treatment card is just the
    plain Pokemon name (e.g. tcgcsv's 'Dhelmise V (Full Art)' becomes cleanName 'Dhelmise V Full
    Art', but pokemontcg.io calls it 'Dhelmise V'). Only strips a known, finite whitelist of
    treatment words tcgcsv actually uses, and only as a trailing suffix, so it can never clip a
    Pokemon name that happens to contain one of these words elsewhere.

    Picks the *longest* matching suffix rather than the first one in the whitelist, since some
    entries are prefixes of others (e.g. 'full art' is a suffix of 'alternate full art') -- taking
    the shorter one first would strip too little and leave a residual word ('Alternate') that
    still fails to match.
    """
    lowered = clean_name.lower()
    matches = [s for s in _KNOWN_TREATMENT_SUFFIXES if lowered.endswith(" " + s)]
    if not matches:
        return clean_name
    longest = max(matches, key=len)
    return clean_name[: -(len(longest) + 1)]


@dataclass(slots=True)
class TaggedMatch:
    """A product whose name carries bracketed tags, resolved to the card it belongs to.

    `printing` is None when every tag was a name tag: the product is then simply the card's own
    product (its Normal/Holo/Reverse printings). Otherwise it is the tagged printing it sells.
    """

    ptcg_card_id: str
    tcgplayer_product_id: int
    printing: "Printing | None"
    tags: list[str]


@dataclass(slots=True)
class UnresolvedProduct:
    tcgplayer_product_id: int
    name: str
    reason: str
    unknown_tags: list[str]


_TAG = re.compile(r"\(([^()]*)\)")
# " - 027", " - 027/078", " - SWSH241", " - BW48" -- the number tcgcsv puts in a promo's name.
_NAME_NUMBER = re.compile(r"\s+-\s+[A-Za-z]*\d+[A-Za-z]*(?:/[A-Za-z]*\d+)?(?=\s|$)")


def split_product_name(name: str) -> tuple[str, list[str]]:
    """'Crobat - BW51 (Team Plasma) (Prerelease)' -> ('Crobat', ['Team Plasma', 'Prerelease'])."""
    tags = [t.strip() for t in _TAG.findall(name)]
    base = _NAME_NUMBER.sub("", _TAG.sub(" ", name))
    return re.sub(r"\s+", " ", base).strip(), tags


def match_tagged_products(
    cards, products, matched_product_ids: set[int], registry
) -> tuple[list[TaggedMatch], list[UnresolvedProduct]]:
    """Second pass for the products `match_cards_in_set` could not pin to a card: the ones whose
    name carries bracketed tags ("Aerodactyl (Delta Species)", "Pikachu - 027 (Prerelease)").

    Each tag is classified by data/printing_tags.yaml. Name tags are stripped; at most one
    printing remains (two printing tags are looked up as their " + " combination). The product
    then matches the card with the same normalized number and name. Anything that does not
    resolve cleanly -- an unknown tag, no such card, two printings with no combined entry -- is
    returned as unresolved with its reason, never guessed.
    """
    by_key: dict[tuple[str | None, str], list] = {}
    for card in cards:
        key = (normalize_number(card.number), normalize_name(card.name))
        by_key.setdefault(key, []).append(card)

    matches: list[TaggedMatch] = []
    unresolved: list[UnresolvedProduct] = []
    for product in products:
        if product.card_number is None or product.tcgplayer_product_id in matched_product_ids:
            continue
        base, tags = split_product_name(product.name)
        if not tags:
            continue

        printing_tags: list[str] = []
        unknown: list[str] = []
        for tag in tags:
            kind = registry.classify(tag).kind
            if kind == "printing":
                printing_tags.append(tag)
            elif kind == "unknown":
                unknown.append(tag)
        if unknown:
            unresolved.append(
                UnresolvedProduct(
                    product.tcgplayer_product_id, product.name, "unknown tag", unknown
                )
            )
            continue

        printing = None
        if printing_tags:
            found = registry.classify(" + ".join(printing_tags))
            if found.printing is None:
                unresolved.append(
                    UnresolvedProduct(
                        product.tcgplayer_product_id,
                        product.name,
                        "several printing tags with no combined entry",
                        [],
                    )
                )
                continue
            printing = found.printing

        candidates = by_key.get((normalize_number(product.card_number), normalize_name(base)), [])
        if len(candidates) != 1:
            reason = "no card with this number and name" if not candidates else "ambiguous card"
            unresolved.append(
                UnresolvedProduct(product.tcgplayer_product_id, product.name, reason, [])
            )
            continue
        matches.append(
            TaggedMatch(candidates[0].ptcg_card_id, product.tcgplayer_product_id, printing, tags)
        )
    return matches, unresolved


def match_cards_in_set(cards, products) -> list[MatchResult]:
    """Match each card in a set to its tcgcsv product, on normalized number then verified name.

    One `MatchResult` per card (not per product), so a card with no matching product is still
    reported -- never silently dropped, per the "never let mismatches be silent" rule in
    docs/03-data-sources.md. `cards` are `Card` ORM rows (`.ptcg_card_id`, `.number`, `.name`);
    `products` are `ProductDTO`s (`.tcgplayer_product_id`, `.card_number`, `.clean_name`) already
    filtered to a single set's tcgcsv group by the caller.
    """
    by_number: dict[str | None, list] = {}
    for product in products:
        if product.card_number is None:
            continue
        by_number.setdefault(normalize_number(product.card_number), []).append(product)

    results: list[MatchResult] = []
    for card in cards:
        candidates = by_number.get(normalize_number(card.number), [])
        card_name = normalize_name(card.name)

        if not candidates:
            results.append(MatchResult(card.ptcg_card_id, None, 0.0, "no number match"))
            continue

        name_matches = [
            p
            for p in candidates
            if normalize_name(
                strip_known_treatment_suffix(
                    strip_disambiguating_number(p.clean_name, p.card_number)
                )
            )
            == card_name
        ]

        if len(name_matches) == 1:
            results.append(
                MatchResult(card.ptcg_card_id, name_matches[0].tcgplayer_product_id, 1.0, "matched")
            )
        elif len(candidates) == 1:
            product = candidates[0]
            results.append(
                MatchResult(
                    card.ptcg_card_id,
                    product.tcgplayer_product_id,
                    0.5,
                    f"number matched, name differs: {card.name!r} vs {product.clean_name!r}",
                )
            )
        else:
            results.append(MatchResult(card.ptcg_card_id, None, 0.5, "ambiguous number match"))
    return results
