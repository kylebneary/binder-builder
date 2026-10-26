import pytest
from app.api.deps import get_db
from app.main import app
from conftest import create_test_schema, seed_catalogue
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

API = "/api/v1"


@pytest.fixture
def ctx():
    """The catalogue fixture behind a TestClient, with the seeded rows returned alongside it."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    create_test_schema(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with Session(engine, expire_on_commit=False) as seed:
        cat = seed_catalogue(seed)
    yield TestClient(app), cat
    app.dependency_overrides.clear()
    engine.dispose()


def test_search_returns_cards_with_set_and_matching_variants(ctx):
    client, cat = ctx
    r = client.post(f"{API}/cards/search", json={"pokedex_numbers": [25], "sort": "oldest"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3 and body["unplaceable_count"] == 1
    first = body["cards"][0]
    assert first["name"] == "Pikachu" and first["set_name"] == "Base"
    assert [v["id"] for v in first["variants"]] == [cat.pikachu_normal.id]


def test_search_validates_enums_and_limits(ctx):
    client, _ = ctx
    assert client.post(f"{API}/cards/search", json={"owned": "maybe"}).status_code == 422
    assert client.post(f"{API}/cards/search", json={"limit": 5000}).status_code == 422


def test_facets(ctx):
    client, _ = ctx
    r = client.get(f"{API}/cards/facets")
    assert r.status_code == 200
    species = {s["pokedex_number"]: s["name"] for s in r.json()["species"]}
    assert species[25] == "Pikachu"


def test_create_live_filter_goal_from_a_query(ctx):
    client, _ = ctx
    r = client.post(
        f"{API}/goals",
        json={
            "name": "Every Arita",
            "goal_type": "filter",
            "query": {"artists": ["Mitsuhiro Arita"], "owned": "missing"},
        },
    )
    assert r.status_code == 201, r.text
    goal = r.json()
    assert goal["filter_json"] == {"artists": ["Mitsuhiro Arita"]}  # ownership dropped
    detail = client.get(f"{API}/goals/{goal['id']}").json()
    assert len(detail["items"]) == 3


def test_create_custom_goal_snapshots_a_query_plus_picked_cards(ctx):
    client, cat = ctx
    r = client.post(
        f"{API}/goals",
        json={
            "name": "Missing electric",
            "goal_type": "custom",
            "card_variant_ids": [cat.ho_oh_normal.id],
            "query": {"types": ["Lightning"], "owned": "missing"},
        },
    )
    assert r.status_code == 201, r.text
    detail = client.get(f"{API}/goals/{r.json()['id']}").json()
    names = {i["card_name"] for i in detail["items"]}
    # The snapshot honours "missing": the owned Pikachu ex is not in it.
    assert names == {"Pikachu", "Electabuzz", "Pikachu & Zekrom-GX", "Ho-Oh"}


def test_empty_filter_goal_is_422(ctx):
    client, _ = ctx
    r = client.post(f"{API}/goals", json={"name": "All", "goal_type": "filter", "query": {}})
    assert r.status_code == 422


def test_edit_items_add_by_query_and_remove(ctx):
    client, cat = ctx
    goal = client.post(f"{API}/goals", json={"name": "Mine", "goal_type": "custom"}).json()
    r = client.post(
        f"{API}/goals/{goal['id']}/items",
        json={"add_query": {"types": ["Fire"]}, "remove": []},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"added": 2, "removed": 0, "item_count": 2}
    r = client.post(f"{API}/goals/{goal['id']}/items", json={"remove": [cat.ho_oh_normal.id]})
    assert r.json()["item_count"] == 1


def test_edit_items_on_a_set_goal_is_409_until_converted(ctx):
    client, cat = ctx
    goal = client.post(
        f"{API}/goals", json={"name": "Base", "goal_type": "set", "set_id": cat.base.id}
    ).json()
    body = {"remove": [cat.pikachu_normal.id]}
    assert client.post(f"{API}/goals/{goal['id']}/items", json=body).status_code == 409

    converted = client.post(f"{API}/goals/{goal['id']}/convert-to-custom")
    assert converted.json()["goal_type"] == "custom"
    r = client.post(f"{API}/goals/{goal['id']}/items", json=body)
    assert r.status_code == 200 and r.json()["item_count"] == 1


def test_edit_items_with_unknown_ids_is_422(ctx):
    client, _ = ctx
    goal = client.post(f"{API}/goals", json={"name": "Mine", "goal_type": "custom"}).json()
    r = client.post(f"{API}/goals/{goal['id']}/items", json={"add": [999999]})
    assert r.status_code == 422


def test_resync_endpoint(ctx):
    client, _ = ctx
    goal = client.post(
        f"{API}/goals", json={"name": "Fire", "goal_type": "filter", "query": {"types": ["Fire"]}}
    ).json()
    assert client.post(f"{API}/goals/{goal['id']}/resync").status_code == 200
    assert client.post(f"{API}/goals/999999/resync").status_code == 404


def test_auto_layout_from_a_goal_and_source_validation(ctx):
    client, cat = ctx
    goal = client.post(
        f"{API}/goals",
        json={"name": "Two", "goal_type": "custom", "card_variant_ids": [cat.pikachu_normal.id]},
    ).json()
    binder = client.post(f"{API}/binders", json={"name": "B"}).json()

    r = client.post(f"{API}/binders/{binder['id']}/auto-layout", json={"goal_id": goal["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["placed"] == 1

    both = {"goal_id": goal["id"], "set_id": cat.base.id}
    assert client.post(f"{API}/binders/{binder['id']}/auto-layout", json=both).status_code == 422
    assert client.post(f"{API}/binders/{binder['id']}/auto-layout", json={}).status_code == 422
    missing = {"goal_id": 999999}
    assert client.post(f"{API}/binders/{binder['id']}/auto-layout", json=missing).status_code == 404
    assert client.post(f"{API}/binders/{binder['id']}/michi-layout", json={}).status_code == 422
