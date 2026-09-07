import pytest
from app.db import enable_sqlite_foreign_keys
from app.models import Base
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Mirror the CREATE VIEWs in backend/migrations/versions/ -- create_all() only builds tables from
# ORM models, never views, so tests need them declared here too. Kept as literals rather than
# imported from the migrations, which are frozen snapshots and must not follow app code; the
# safety net against drift is behavioural (see
# test_service_portfolio.test_collection_holding_view_agrees_with_the_default_grouping).
_CURRENT_PRICE_VIEW_SQL = """
CREATE VIEW current_price AS
SELECT p.*
FROM price_point p
INNER JOIN (
    SELECT tcgplayer_product_id, sub_type_name, MAX(observed_on) AS max_observed_on
    FROM price_point
    GROUP BY tcgplayer_product_id, sub_type_name
) latest
ON p.tcgplayer_product_id = latest.tcgplayer_product_id
AND p.sub_type_name = latest.sub_type_name
AND p.observed_on = latest.max_observed_on
"""


# b7e2d5a91c04. The default roll-up of physical rows into holdings; SUM(quantity), not COUNT(*),
# because a row with no location can stand for N indistinguishable copies.
_COLLECTION_HOLDING_VIEW_SQL = """
CREATE VIEW collection_holding AS
SELECT
    collection_id,
    card_variant_id,
    condition,
    language,
    is_graded,
    grade,
    SUM(quantity) AS quantity,
    COUNT(*) AS copy_rows,
    COUNT(storage_location) AS located_copies,
    MIN(storage_location) AS first_location,
    SUM(acquired_price * quantity) AS acquired_total
FROM collection_item
GROUP BY collection_id, card_variant_id, condition, language, is_graded, grade
"""


def create_test_schema(engine) -> None:
    """Every table, both views, and SQLite's foreign keys switched on.

    The FK pragma matters: without it SQLite ignores every ondelete="CASCADE" and tests pass
    against behaviour production does not have. See app/db.py.

    create_all (not Alembic) is fine here -- tests are the documented exception in
    docs/02-data-model.md ("do not use create_all outside tests").
    """
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_CURRENT_PRICE_VIEW_SQL))
        conn.execute(text(_COLLECTION_HOLDING_VIEW_SQL))


@pytest.fixture
def db() -> Session:
    """In-memory SQLite session with the full test schema."""
    engine = create_engine("sqlite:///:memory:")
    create_test_schema(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
