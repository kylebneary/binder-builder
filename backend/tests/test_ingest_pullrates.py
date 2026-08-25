from pathlib import Path

from app.ingest.pullrates import load_pull_rate_profiles, sync_pull_rates_to_db
from app.models import Card, PackSlot, PullRateProfile, Set
from sqlalchemy import func, select

_VALID_PROFILE = """
set: sv8
name: "Surging Sparks - standard booster"
cards_per_pack: 2
confidence: low
sample_packs: 100
source_urls:
  - https://example.com/source
notes: "test fixture"
slots:
  - index: 1
    label: common
    repeat: 1
    outcomes:
      - {rarity: "Common", probability: 1.0}
  - index: 2
    label: hit
    repeat: 1
    outcomes:
      - {rarity: "Common", probability: 0.5}
      - {rarity: "Rare", probability: 0.5}
box_constraints: []
"""

_BAD_PROBABILITY_PROFILE = """
set: sv9
name: "Bad probability sum"
cards_per_pack: 1
slots:
  - index: 1
    label: hit
    repeat: 1
    outcomes:
      - {rarity: "Common", probability: 0.5}
      - {rarity: "Rare", probability: 0.4}
box_constraints: []
"""

_BAD_REPEAT_PROFILE = """
set: sv10
name: "Bad repeat sum"
cards_per_pack: 5
slots:
  - index: 1
    label: common
    repeat: 1
    outcomes:
      - {rarity: "Common", probability: 1.0}
box_constraints: []
"""


def _seed_set_with_rarities(db, ptcg_set_id: str, rarities: list[str]) -> Set:
    set_row = Set(ptcg_set_id=ptcg_set_id, name="Test Set")
    db.add(set_row)
    db.flush()
    for i, rarity in enumerate(rarities):
        db.add(
            Card(
                ptcg_card_id=f"{ptcg_set_id}-{i}",
                set_id=set_row.id,
                number=str(i),
                number_sort=i,
                name=f"Card {i}",
                rarity=rarity,
            )
        )
    db.commit()
    return set_row


def test_load_pull_rate_profiles_skips_template_and_example(tmp_path: Path):
    (tmp_path / "_TEMPLATE.yaml").write_text(_BAD_REPEAT_PROFILE, encoding="utf-8")
    (tmp_path / "EXAMPLE-sv8.yaml").write_text(_VALID_PROFILE, encoding="utf-8")
    (tmp_path / "sv8.yaml").write_text(_VALID_PROFILE, encoding="utf-8")

    profiles = load_pull_rate_profiles(tmp_path)
    assert set(profiles.keys()) == {"sv8"}
    assert profiles["sv8"].source_file == "sv8.yaml"


def test_load_pull_rate_profiles_missing_directory_returns_empty(tmp_path: Path):
    assert load_pull_rate_profiles(tmp_path / "does-not-exist") == {}


def test_load_pull_rate_profiles_rejects_bad_probability_sum(tmp_path: Path, caplog):
    (tmp_path / "sv9.yaml").write_text(_BAD_PROBABILITY_PROFILE, encoding="utf-8")
    profiles = load_pull_rate_profiles(tmp_path)
    assert profiles == {}
    assert "invalid pull-rate profile" in caplog.text


def test_load_pull_rate_profiles_rejects_bad_repeat_sum(tmp_path: Path, caplog):
    (tmp_path / "sv10.yaml").write_text(_BAD_REPEAT_PROFILE, encoding="utf-8")
    profiles = load_pull_rate_profiles(tmp_path)
    assert profiles == {}
    assert "invalid pull-rate profile" in caplog.text


def test_sync_reports_no_set_row_when_set_missing(tmp_path: Path, db):
    (tmp_path / "sv8.yaml").write_text(_VALID_PROFILE, encoding="utf-8")
    profiles = load_pull_rate_profiles(tmp_path)
    results = sync_pull_rates_to_db(db, profiles)
    assert results[0].status == "no_set_row"


def test_sync_rejects_unknown_rarity(tmp_path: Path, db):
    _seed_set_with_rarities(db, "sv8", ["Common"])  # missing "Rare"
    (tmp_path / "sv8.yaml").write_text(_VALID_PROFILE, encoding="utf-8")
    profiles = load_pull_rate_profiles(tmp_path)
    results = sync_pull_rates_to_db(db, profiles)
    assert results[0].status.startswith("invalid: unknown rarity")
    assert db.execute(select(func.count()).select_from(PullRateProfile)).scalar_one() == 0


def test_sync_creates_profile_and_is_idempotent(tmp_path: Path, db):
    _seed_set_with_rarities(db, "sv8", ["Common", "Rare"])
    (tmp_path / "sv8.yaml").write_text(_VALID_PROFILE, encoding="utf-8")
    profiles = load_pull_rate_profiles(tmp_path)

    results = sync_pull_rates_to_db(db, profiles)
    assert results[0].status == "synced"

    profile = db.execute(select(PullRateProfile)).scalar_one()
    assert profile.cards_per_pack == 2
    assert profile.source_file == "sv8.yaml"
    assert len(profile.slots) == 2

    # Resync must not duplicate child rows.
    results2 = sync_pull_rates_to_db(db, profiles)
    assert results2[0].status == "synced"
    assert db.execute(select(func.count()).select_from(PullRateProfile)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(PackSlot)).scalar_one() == 2
