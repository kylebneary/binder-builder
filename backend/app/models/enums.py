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
    UNLIMITED_HOLOFOIL = "unlimited_holofoil"
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
    SET = "set"
    MASTER_SET = "master_set"
    FILTER = "filter"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PlacementKind(StrEnum):
    CARD = "card"
    INSERT = "insert"
    EMPTY = "empty"
