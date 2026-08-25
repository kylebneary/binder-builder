"""Read-only helpers over the `current_price` view (see docs/02-data-model.md)."""
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class CurrentPrice(TypedDict):
    low: Decimal | None
    mid: Decimal | None
    high: Decimal | None
    market: Decimal | None
    direct_low: Decimal | None
    observed_on: str | None


def _to_decimal(value: object) -> Decimal | None:
    """SQLite has no DECIMAL storage type, so a raw (non-ORM-typed) query returns money
    columns as float -- convert through str, never straight from float, to avoid binary
    floating-point error creeping into a currency value. See CLAUDE.md: never float for money.
    """
    if value is None:
        return None
    return Decimal(str(value))


def get_current_prices(db: Session, product_ids: list[int]) -> dict[tuple[int, str], CurrentPrice]:
    """Fetch the latest price row for every (tcgplayer_product_id, sub_type_name) pair under
    the given product ids, keyed the same way `card_variant` is (see the "one rule that
    matters" in docs/02-data-model.md)."""
    if not product_ids:
        return {}
    stmt = text(
        "SELECT tcgplayer_product_id, sub_type_name, low, mid, high, market, direct_low, "
        "observed_on FROM current_price WHERE tcgplayer_product_id IN :product_ids"
    ).bindparams(bindparam("product_ids", expanding=True))
    rows = db.execute(stmt, {"product_ids": product_ids}).mappings().all()
    return {
        (row["tcgplayer_product_id"], row["sub_type_name"]): CurrentPrice(
            low=_to_decimal(row["low"]),
            mid=_to_decimal(row["mid"]),
            high=_to_decimal(row["high"]),
            market=_to_decimal(row["market"]),
            direct_low=_to_decimal(row["direct_low"]),
            observed_on=str(row["observed_on"]) if row["observed_on"] is not None else None,
        )
        for row in rows
    }
