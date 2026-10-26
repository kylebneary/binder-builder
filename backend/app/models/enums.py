from enum import StrEnum


class Variant(StrEnum):
    """Printing variants. Values mirror tcgcsv `subTypeName` where one exists.

    New members are added when the price feed reveals a subTypeName we do not model yet --
    do not guess these ahead of the data.
    """

    NORMAL = "normal"
    HOLOFOIL = "holofoil"
    REVERSE_HOLOFOIL = "reverse_holofoil"
    FIRST_EDITION_NORMAL = "first_edition_normal"
    FIRST_EDITION_HOLOFOIL = "first_edition_holofoil"
    UNLIMITED_NORMAL = "unlimited_normal"
    UNLIMITED_HOLOFOIL = "unlimited_holofoil"
    # Base Set's early unlimited run, sold by TCGplayer as its own group ("Base Set
    # (Shadowless)") rather than as a subTypeName -- see edition_groups in printing_tags.yaml.
    SHADOWLESS_NORMAL = "shadowless_normal"
    SHADOWLESS_HOLOFOIL = "shadowless_holofoil"
    POKE_BALL_HOLO = "poke_ball_holo"
    MASTER_BALL_HOLO = "master_ball_holo"


class Condition(StrEnum):
    NM = "NM"
    LP = "LP"
    MP = "MP"
    HP = "HP"
    DMG = "DMG"


class ProductType(StrEnum):
    BOOSTER_PACK = "booster_pack"
    BOOSTER_BUNDLE = "booster_bundle"
    BLISTER_3PACK = "blister_3pack"
    BOOSTER_BOX = "booster_box"
    ETB = "etb"
    ULTRA_PREMIUM_COLLECTION = "ultra_premium_collection"
    SPECIAL_COLLECTION = "special_collection"
    TIN = "tin"
    CASE = "case"
    OTHER = "other"


class GoalType(StrEnum):
    """How a goal's `goal_item` rows are decided.

    SET / MASTER_SET / GRAND_MASTER_SET / FILTER are rules, re-materialised on resync, so a
    filter goal like "every Pikachu" picks up cards from newly ingested sets. CUSTOM has no rule:
    its items *are* the goal, edited one by one, and resync leaves them alone.

    SET is one canonical printing per card; MASTER_SET adds every printing pulled from the set's
    packs (reverse holos, Poké Ball patterns); GRAND_MASTER_SET adds the stamps and promo
    printings too (`card_variant.is_special`).
    """

    SET = "set"
    MASTER_SET = "master_set"
    GRAND_MASTER_SET = "grand_master_set"
    FILTER = "filter"
    CUSTOM = "custom"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PlacementKind(StrEnum):
    CARD = "card"
    INSERT = "insert"
    EMPTY = "empty"
