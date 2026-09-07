import pytest
from app.db import enable_sqlite_foreign_keys
from app.models import Base
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Mirrors the CREATE VIEW in backend/migrations/versions/c8364ca2a717_baseline_schema.py --
# create_all() only builds tables from ORM models, never the view, so tests need it too.
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


@pytest.fixture
def db() -> Session:
    """In-memory SQLite session with all tables (+ the current_price view) created.

    create_all (not Alembic) is fine here -- tests are the documented exception in
    docs/02-data-model.md ("do not use create_all outside tests").
    """
    engine = create_engine("sqlite:///:memory:")
    # Match the app engine: without this, SQLite ignores every ondelete="CASCADE" and tests
    # would pass against behaviour production does not have. See app/db.py.
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_CURRENT_PRICE_VIEW_SQL))
    with Session(engine) as session:
        yield session
    engine.dispose()
