from datetime import date

from app.ingest.base import SetDTO
from app.ingest.set_mapping import (
    SetMatchResult,
    load_set_map,
    match_sets,
    merge_set_map,
    normalize_group_name,
)


def _set(ptcg_set_id: str, name: str, release_date: date | None = None) -> SetDTO:
    return SetDTO(
        ptcg_set_id=ptcg_set_id,
        name=name,
        series=None,
        printed_total=None,
        total=None,
        release_date=release_date,
        ptcgo_code=None,
        symbol_url=None,
        logo_url=None,
    )


def _group(group_id: int, name: str, published_on: str | None = None) -> dict:
    return {"groupId": group_id, "name": name, "publishedOn": published_on}


def test_normalize_group_name_strips_era_code_prefix():
    assert normalize_group_name("SV08: Surging Sparks") == "surging sparks"
    assert normalize_group_name("ME: 30th Celebration") == "30th celebration"
    assert normalize_group_name("Base Set") == "base set"


def test_match_sets_happy_path_with_code_prefix_and_date():
    sets = [_set("sv8", "Surging Sparks", date(2024, 11, 8))]
    groups = [
        _group(23651, "SV08: Surging Sparks", "2024-11-08T00:00:00"),
        _group(99999, "Unrelated Product Line", "2024-01-01T00:00:00"),
    ]
    results = match_sets(sets, groups)
    assert results == [SetMatchResult("sv8", 23651, 1.0, "matched")]


def test_match_sets_no_confident_match_for_supplemental_group():
    sets = [_set("sv8", "Surging Sparks", date(2024, 11, 8))]
    groups = [_group(1, "Trainer Toolkit Accessories", "2024-11-08T00:00:00")]
    results = match_sets(sets, groups)
    r = results[0]
    assert r.tcgplayer_group_id is None
    assert r.confidence == 0.0
    assert r.reason == "no confident tcgcsv match"


def test_match_sets_ambiguous_when_two_candidates_score_close():
    # Two groups with the exact same normalized name and no date data to disambiguate.
    sets = [_set("sv8", "Surging Sparks", None)]
    groups = [
        _group(1, "SV08: Surging Sparks", None),
        _group(2, "XX08: Surging Sparks", None),
    ]
    results = match_sets(sets, groups)
    r = results[0]
    assert r.tcgplayer_group_id is None
    assert r.confidence == 0.5
    assert "ambiguous" in r.reason


def test_match_sets_date_breaks_a_near_tie():
    # Same base name text similarity, but one group's date lines up and the other doesn't.
    sets = [_set("sv8", "Surging Sparks", date(2024, 11, 8))]
    groups = [
        _group(1, "SV08: Surging Sparks", "2024-11-08T00:00:00"),
        _group(2, "SV08: Surging Sparks Reprint", "2030-01-01T00:00:00"),
    ]
    results = match_sets(sets, groups)
    r = results[0]
    assert r.tcgplayer_group_id == 1
    assert r.confidence == 1.0


def test_match_sets_reports_every_set_never_silent():
    sets = [
        _set("sv8", "Surging Sparks", date(2024, 11, 8)),
        _set("made-up", "Totally Fictional Set", date(2024, 1, 1)),
    ]
    groups = [_group(23651, "SV08: Surging Sparks", "2024-11-08T00:00:00")]
    results = match_sets(sets, groups)
    assert {r.ptcg_set_id for r in results} == {"sv8", "made-up"}


def test_merge_set_map_never_overwrites_existing_entries(tmp_path):
    path = tmp_path / "set_map.yaml"
    path.write_text("sv8: 23651\n")

    # A re-run that would "correct" sv8 to something else must not touch the hand-set value,
    # but new keys are still added.
    merged = merge_set_map(path, {"sv8": 99999, "sv7": 11111})
    assert merged == {"sv8": 23651, "sv7": 11111}
    assert load_set_map(path) == {"sv8": 23651, "sv7": 11111}


def test_merge_set_map_is_idempotent(tmp_path):
    path = tmp_path / "set_map.yaml"
    merge_set_map(path, {"sv8": 23651})
    first_contents = path.read_text()
    merge_set_map(path, {"sv8": 23651})
    assert path.read_text() == first_contents


def test_load_set_map_missing_file_returns_empty(tmp_path):
    assert load_set_map(tmp_path / "does_not_exist.yaml") == {}
