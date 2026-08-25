"""Joining pokemontcg.io cards to TCGplayer product IDs.

There is no shared key. This is the hardest correctness problem in Phase 1 -- see
docs/06-roadmap.md "Where the hard parts are". Unmatched rows go to a review queue.
They must never fail silently, because a silent mismatch yields confidently wrong prices.
"""
import re
from dataclasses import dataclass


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
            if normalize_name(strip_disambiguating_number(p.clean_name, p.card_number))
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
