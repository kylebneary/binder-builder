from datetime import date

import pytest
from app.api.deps import get_db
from app.main import app
from app.models import Base, Card, CardVariant, PricePoint, Set
from app.models.enums import Variant
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Mirrors backend/migrations/versions/c8364ca2a717_baseline_schema.py -- see the same note in
# conftest.py's db fixture.
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
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_CURRENT_PRICE_VIEW_SQL))
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with Session(engine) as seed_session:
        set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", release_date=date(2024, 11, 8))
        seed_session.add(set_row)
        seed_session.flush()
        card = Card(
            ptcg_card_id="sv8-122",
            set_id=set_row.id,
            number="122",
            number_sort=122,
            name="Alolan Diglett",
        )
        seed_session.add(card)
        seed_session.flush()
        variant = CardVariant(
            card_id=card.id,
            variant=Variant.NORMAL,
            tcgplayer_product_id=589855,
            tcgplayer_sub_type_name="Normal",
            is_canonical=True,
        )
        seed_session.add(variant)
        seed_session.add(
            PricePoint(
                tcgplayer_product_id=589855,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=0.06,
            )
        )
        seed_session.commit()

    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_sets(client):
    r = client.get("/api/v1/sets")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["ptcg_set_id"] == "sv8"


def test_get_set_detail(client):
    r = client.get("/api/v1/sets/sv8")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Surging Sparks"
    assert len(body["cards"]) == 1
    assert body["cards"][0]["variants"][0]["market_price"] == "0.06"
    assert body["owned_count"] == 0
    assert body["needed_count"] == 1


def test_get_set_detail_404(client):
    r = client.get("/api/v1/sets/does-not-exist")
    assert r.status_code == 404


def test_collection_crud_and_portfolio_roundtrip(client):
    r = client.get("/api/v1/sets/sv8")
    variant_id = r.json()["cards"][0]["variants"][0]["id"]

    r = client.put(
        "/api/v1/collection/items",
        json={"card_variant_id": variant_id, "quantity": 3, "acquired_price": "1.00"},
    )
    assert r.status_code == 200
    item = r.json()
    assert item["quantity"] == 3

    r = client.get("/api/v1/collection/items")
    assert len(r.json()) == 1

    r = client.get("/api/v1/collection/portfolio")
    summary = r.json()
    assert summary["total_market_value"] == "0.18"  # 3 * 0.06
    assert summary["total_cost_basis"] == "3.00"  # 3 * 1.00

    # Owned/needed reflects the new holding now.
    r = client.get("/api/v1/sets/sv8")
    assert r.json()["owned_count"] == 1

    r = client.delete(f"/api/v1/collection/items/{item['id']}")
    assert r.status_code == 204
    assert client.get("/api/v1/collection/items").json() == []


def test_delete_missing_item_404(client):
    r = client.delete("/api/v1/collection/items/999999")
    assert r.status_code == 404
