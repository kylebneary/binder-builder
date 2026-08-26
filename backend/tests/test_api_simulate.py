from datetime import date

import pytest
from app.api.deps import get_db
from app.main import app
from app.models import (
    Base,
    Card,
    CardVariant,
    PackSlot,
    PricePoint,
    PullRateProfile,
    SealedProduct,
    Set,
    SlotOutcome,
)
from app.models.enums import Variant
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
    with Session(engine) as seed:
        set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", release_date=date(2024, 11, 8))
        seed.add(set_row)
        seed.flush()

        card = Card(
            ptcg_card_id="sv8-1", set_id=set_row.id, number="1", number_sort=1,
            name="Charizard", rarity="Rare",
        )
        seed.add(card)
        seed.flush()
        variant = CardVariant(
            card_id=card.id, variant=Variant.HOLOFOIL, tcgplayer_product_id=1001,
            tcgplayer_sub_type_name="Holofoil", is_canonical=True,
        )
        seed.add(variant)
        seed.add(
            PricePoint(
                tcgplayer_product_id=1001, sub_type_name="Holofoil",
                observed_on=date(2026, 8, 25), source="tcgcsv", market=20.00,
            )
        )

        profile = PullRateProfile(
            set_id=set_row.id, name="Surging Sparks - standard booster", cards_per_pack=1,
            is_default=True,
        )
        seed.add(profile)
        seed.flush()
        seed.add(
            PackSlot(
                profile_id=profile.id, slot_index=1, label="rare", repeat=1,
                outcomes=[SlotOutcome(rarity="Rare", probability=1.0, variant="holofoil")],
            )
        )

        sealed = SealedProduct(
            set_id=set_row.id, tcgplayer_product_id=2001, name="Booster Box", packs_per_unit=4,
        )
        seed.add(sealed)
        seed.add(
            PricePoint(
                tcgplayer_product_id=2001, sub_type_name="Normal",
                observed_on=date(2026, 8, 25), source="tcgcsv", market=5.00,
            )
        )
        seed.commit()

    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def test_list_sealed_products_flags_pull_rate_coverage(client):
    r = client.get("/api/v1/sets/sv8/sealed-products")
    assert r.status_code == 200
    products = r.json()
    assert len(products) == 1
    assert products[0]["name"] == "Booster Box"
    assert products[0]["has_pull_rate_profile"] is True
    assert float(products[0]["market_price"]) == 5.00


def test_list_sealed_products_404_for_missing_set(client):
    r = client.get("/api/v1/sets/does-not-exist/sealed-products")
    assert r.status_code == 404


def test_simulate_goal_returns_ranked_strategies_with_baseline(client):
    r = client.get("/api/v1/sets/sv8")
    set_id = r.json()["id"]
    r = client.post(
        "/api/v1/goals",
        json={"name": "Surging Sparks master set", "goal_type": "master_set", "set_id": set_id},
    )
    goal_id = r.json()["id"]

    r = client.post(f"/api/v1/goals/{goal_id}/simulate", json={"n_trials": 1000})
    assert r.status_code == 200
    body = r.json()
    assert body["objective"] == "min_expected_cost"
    assert not body["unsimulatable"]
    strategies = [tuple(sorted(item["strategy"]["units"].items())) for item in body["ranked"]]
    assert () in strategies
    means = [item["result"]["mean"] for item in body["ranked"]]
    assert means == sorted(means)


def test_simulate_goal_invalid_objective_422(client):
    r = client.get("/api/v1/sets/sv8")
    set_id = r.json()["id"]
    r = client.post(
        "/api/v1/goals",
        json={"name": "Surging Sparks master set", "goal_type": "master_set", "set_id": set_id},
    )
    goal_id = r.json()["id"]

    r = client.post(
        f"/api/v1/goals/{goal_id}/simulate", json={"objective": "not-a-real-objective"}
    )
    assert r.status_code == 422


def test_simulate_goal_404_for_missing_goal(client):
    r = client.post("/api/v1/goals/999999/simulate", json={})
    assert r.status_code == 404
