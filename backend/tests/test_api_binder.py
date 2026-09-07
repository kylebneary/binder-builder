from datetime import date

import pytest
from app.api.deps import get_db
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.models import Base, Card, CardVariant, Collection, CollectionItem, Set
from app.models.enums import Variant
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

API = "/api/v1"


@pytest.fixture
def client():
    """Same in-memory app wiring as test_api.py, seeded with a four-card set and a collection
    holding exactly one of them, so the not-owned roll-up has something to count."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
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
        for i in range(1, 5):
            card = Card(
                ptcg_card_id=f"sv8-{i:03d}",
                set_id=set_row.id,
                number=f"{i:03d}",
                number_sort=i,
                name=f"Card {i}",
                rarity="Common",
            )
            seed.add(card)
            seed.flush()
            seed.add(
                CardVariant(
                    card_id=card.id,
                    variant=Variant.NORMAL,
                    tcgplayer_product_id=100000 + i,
                    tcgplayer_sub_type_name="Normal",
                    is_canonical=True,
                )
            )
        collection = Collection(name="My Collection", is_default=True)
        seed.add(collection)
        seed.flush()
        seed.add(CollectionItem(collection_id=collection.id, card_variant_id=1, quantity=1))
        seed.commit()

    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def _create(client, **kw) -> dict:
    body = {"name": "Test binder", **kw}
    r = client.post(f"{API}/binders", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list_binders(client):
    created = _create(client)
    assert created["rows"] == 3 and created["cols"] == 3

    r = client.get(f"{API}/binders")
    assert r.status_code == 200
    assert [b["id"] for b in r.json()] == [created["id"]]


def test_get_binder(client):
    binder = _create(client, name="Surging Sparks master")
    r = client.get(f"{API}/binders/{binder['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "Surging Sparks master"


def test_get_missing_binder_is_404(client):
    assert client.get(f"{API}/binders/999").status_code == 404


def test_patch_binder(client):
    binder = _create(client)
    r = client.patch(
        f"{API}/binders/{binder['id']}",
        json={"name": "Renamed", "rows": 3, "cols": 4, "pages": 30},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["cols"] == 4


def test_delete_binder(client):
    binder = _create(client)
    assert client.delete(f"{API}/binders/{binder['id']}").status_code == 204
    assert client.get(f"{API}/binders/{binder['id']}").status_code == 404
    assert client.delete(f"{API}/binders/{binder['id']}").status_code == 404


def test_layout_of_an_empty_binder(client):
    binder = _create(client)
    r = client.get(f"{API}/binders/{binder['id']}/layout")
    assert r.status_code == 200
    body = r.json()
    assert body["placements"] == []
    assert body["not_owned_count"] == 0


def test_put_placements_writes_a_batch(client):
    binder = _create(client)
    r = client.put(
        f"{API}/binders/{binder['id']}/placements",
        json={
            "upserts": [
                {"page_index": 0, "row": 0, "col": 0, "kind": "card", "card_variant_id": 1},
                {"page_index": 0, "row": 0, "col": 1, "kind": "card", "card_variant_id": 2},
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2

    layout = client.get(f"{API}/binders/{binder['id']}/layout").json()
    assert len(layout["placements"]) == 2
    assert layout["not_owned_count"] == 1  # only card_variant 1 is held


def test_a_batch_that_breaks_an_invariant_is_409_with_every_violation(client):
    binder = _create(client)
    r = client.put(
        f"{API}/binders/{binder['id']}/placements",
        json={
            "upserts": [
                {"page_index": 0, "row": 0, "col": 0, "kind": "card"},
                {"page_index": 0, "row": 9, "col": 9, "kind": "card", "card_variant_id": 2},
            ]
        },
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert len(detail) >= 2
    assert client.get(f"{API}/binders/{binder['id']}/layout").json()["placements"] == []


def test_gutter_span_in_a_top_loading_binder_is_409(client):
    binder = _create(client, is_side_loading=False)
    r = client.put(
        f"{API}/binders/{binder['id']}/placements",
        json={
            "upserts": [
                {
                    "page_index": 0,
                    "row": 0,
                    "col": 2,
                    "col_span": 2,
                    "kind": "empty",
                    "spans_gutter": True,
                }
            ]
        },
    )
    assert r.status_code == 409
    assert any("side-loading" in e for e in r.json()["detail"])


def test_put_placements_on_a_missing_binder_is_404(client):
    r = client.put(f"{API}/binders/999/placements", json={"upserts": []})
    assert r.status_code == 404


def test_undo_is_one_inverse_batch(client):
    """The gesture and its inverse are each a single request -- that is what 3.12 relies on."""
    binder = _create(client)
    url = f"{API}/binders/{binder['id']}/placements"
    client.put(url, json={"upserts": [
        {"page_index": 0, "row": 0, "col": 0, "kind": "card", "card_variant_id": 1}
    ]})

    # gesture: move (0,0) -> (1,1)
    client.put(url, json={
        "upserts": [{"page_index": 0, "row": 1, "col": 1, "kind": "card", "card_variant_id": 1}],
        "clears": [{"page_index": 0, "row": 0, "col": 0}],
    })
    # inverse
    client.put(url, json={
        "upserts": [{"page_index": 0, "row": 0, "col": 0, "kind": "card", "card_variant_id": 1}],
        "clears": [{"page_index": 0, "row": 1, "col": 1}],
    })

    placements = client.get(f"{API}/binders/{binder['id']}/layout").json()["placements"]
    assert [(p["row"], p["col"]) for p in placements] == [(0, 0)]


def test_delete_a_placement(client):
    binder = _create(client)
    written = client.put(
        f"{API}/binders/{binder['id']}/placements",
        json={"upserts": [
            {"page_index": 0, "row": 0, "col": 0, "kind": "card", "card_variant_id": 1}
        ]},
    ).json()
    pid = written[0]["id"]
    assert client.delete(f"{API}/binders/{binder['id']}/placements/{pid}").status_code == 204
    assert client.delete(f"{API}/binders/{binder['id']}/placements/{pid}").status_code == 404


def test_auto_layout_endpoint(client):
    binder = _create(client)
    r = client.post(f"{API}/binders/{binder['id']}/auto-layout", json={"set_id": 1})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "placed": 4,
        "unplaced": 0,
        "pages_used": 1,
        "skipped_no_variant": 0,
    }

    layout = client.get(f"{API}/binders/{binder['id']}/layout").json()
    assert [p["number"] for p in layout["placements"]] == ["001", "002", "003", "004"]
    assert layout["not_owned_count"] == 3


def test_auto_layout_rejects_an_unknown_mode(client):
    binder = _create(client)
    r = client.post(
        f"{API}/binders/{binder['id']}/auto-layout", json={"set_id": 1, "mode": "michi"}
    )
    assert r.status_code == 422


def test_layout_json_round_trips_over_http(client):
    binder = _create(client)
    client.post(f"{API}/binders/{binder['id']}/auto-layout", json={"set_id": 1})
    payload = client.get(f"{API}/binders/{binder['id']}/layout.json").json()
    assert payload["version"] == 1
    assert len(payload["placements"]) == 4

    target = _create(client, name="Target")
    r = client.post(f"{API}/binders/{target['id']}/layout.json", json=payload)
    assert r.status_code == 200, r.text
    assert len(client.get(f"{API}/binders/{target['id']}/layout").json()["placements"]) == 4


def test_importing_an_unknown_version_is_422(client):
    binder = _create(client)
    r = client.post(
        f"{API}/binders/{binder['id']}/layout.json",
        json={"version": 99, "binder": {}, "placements": []},
    )
    assert r.status_code == 422
