from app.ingest.set_mapping import SetMapSyncResult, sync_set_map_to_db
from app.models import Set
from sqlalchemy import select


def test_sync_set_map_links_and_is_idempotent(db):
    db.add(Set(ptcg_set_id="sv8", name="Surging Sparks"))
    db.commit()

    results1 = sync_set_map_to_db(db, {"sv8": 23651})
    assert results1 == [SetMapSyncResult("sv8", 23651, "linked")]
    set_row = db.execute(select(Set).where(Set.ptcg_set_id == "sv8")).scalar_one()
    assert set_row.tcgplayer_group_id == 23651

    results2 = sync_set_map_to_db(db, {"sv8": 23651})
    assert results2 == [SetMapSyncResult("sv8", 23651, "unchanged")]


def test_sync_set_map_reports_missing_set_row_without_erroring(db):
    results = sync_set_map_to_db(db, {"does-not-exist": 1})
    assert results == [SetMapSyncResult("does-not-exist", 1, "no_set_row")]


def test_sync_set_map_logs_and_updates_when_value_changes(db, caplog):
    db.add(Set(ptcg_set_id="sv8", name="Surging Sparks", tcgplayer_group_id=1))
    db.commit()

    results = sync_set_map_to_db(db, {"sv8": 2})
    assert results == [SetMapSyncResult("sv8", 2, "updated")]
    assert "changing 1 -> 2" in caplog.text
    set_row = db.execute(select(Set).where(Set.ptcg_set_id == "sv8")).scalar_one()
    assert set_row.tcgplayer_group_id == 2
