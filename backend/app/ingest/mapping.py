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


def match_cards_in_set(cards, products) -> list[MatchResult]:
    """Match on normalized number first, verify with normalized name.

    TODO(phase-1.6): implement, and emit a review report of every card with
    confidence < 1.0 or no match at all.
    """
    raise NotImplementedError
