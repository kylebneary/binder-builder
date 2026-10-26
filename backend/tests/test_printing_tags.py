"""Tagged printings: the registry, the second-pass matcher, and how the ingest turns tagged
products into card_variant rows. Product names below are real tcgcsv names from the 2026-10-25
survey (see data/printing_tags.yaml)."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.ingest.base import PricePointDTO, ProductDTO
from app.ingest.mapping import match_tagged_products, split_product_name
from app.ingest.prices import _derive_variants, resolve_group_set_pairs
from app.ingest.printing_tags import TagKind, default_registry, load_registry
from app.models import Card, CardVariant, Set
from sqlalchemy import select

REGISTRY = default_registry()


@pytest.mark.parametrize(
    ("tag", "kind", "slug"),
    [
        ("Delta Species", TagKind.NAME, None),
        ("98 Full Art", TagKind.NAME, None),  # leading number stripped
        ("A", TagKind.NAME, None),  # Unown
        ("H12", TagKind.NAME, None),  # e-Card holo number
        ("002", TagKind.NAME, None),  # bare disambiguator
        ("Poke Ball Pattern", TagKind.PRINTING, "poke_ball_holo"),
        ("Poke Ball", TagKind.PRINTING, "poke_ball_holo"),  # Ascended Heroes spelling
        ("Prerelease", TagKind.PRINTING, "prerelease"),
        ("cosmo holofoil", TagKind.PRINTING, "cosmos_holo"),  # misspelling, any case
        ("Prerelease + Staff", TagKind.PRINTING, "prerelease_staff"),
        ("151 Metal Card", TagKind.PRINTING, "metal_card"),
        ("Mystery Tag", TagKind.UNKNOWN, None),
    ],
)
def test_classify(tag, kind, slug):
    found = REGISTRY.classify(tag)
    assert found.kind == kind
    assert (found.printing.slug if found.printing else None) == slug


@pytest.mark.parametrize(
    ("tag", "slug", "label"),
    [
        ("Worlds 13", "worlds_2013", "Worlds 2013 stamp"),
        ("World Championships 2024", "worlds_2024", "Worlds 2024 stamp"),
        ("2005 World Championships", "worlds_2005", "Worlds 2005 stamp"),
        # Year-led: matched by its pattern before the leading-number rule could eat the year.
        ("2014 Top Thirty-Two", "worlds_2014_top_32", "Worlds 2014 Top 32"),
        ("2016 Champion", "worlds_2016_champion", "Worlds 2016 Champion"),
        ("Battle Road Autumn 2011", "battle_road_autumn_2011", "Battle Road Autumn 2011"),
    ],
)
def test_worlds_and_event_stamps_are_one_printing_per_year(tag, slug, label):
    printing = REGISTRY.classify(tag).printing
    assert printing is not None
    assert (printing.slug, printing.label, printing.is_special) == (slug, label, True)
    assert REGISTRY.label_for(slug) == label


def test_two_worlds_years_are_different_printings():
    a = REGISTRY.classify("World Championships 2023").printing
    b = REGISTRY.classify("World Championships 2024").printing
    assert a is not None and b is not None and a.slug != b.slug


def test_pattern_printings_are_set_scope_and_stamps_are_special():
    assert not REGISTRY.classify("Master Ball Pattern").printing.is_special
    assert REGISTRY.classify("Staff").printing.is_special


def test_label_for_base_variants_is_none():
    assert REGISTRY.label_for("holofoil") is None


def test_every_slug_fits_the_variant_column():
    assert all(len(p.slug) <= 32 for p in REGISTRY.printings.values())


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "tags.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loader_rejects_an_unknown_scope(tmp_path):
    path = _write(tmp_path, "printings:\n  - {tag: X, slug: x, label: X, scope: maybe}\n")
    with pytest.raises(ValueError, match="scope"):
        load_registry(path)


def test_loader_rejects_a_tag_with_two_meanings(tmp_path):
    path = _write(
        tmp_path,
        "printings:\n"
        "  - {tag: X, slug: x, label: X, scope: special}\n"
        "  - {tag: Y, slug: y, label: Y, scope: special, aliases: [X]}\n",
    )
    with pytest.raises(ValueError, match="twice"):
        load_registry(path)


def test_loader_rejects_a_slug_that_shadows_a_base_variant(tmp_path):
    path = _write(tmp_path, "printings:\n  - {tag: X, slug: holofoil, label: X, scope: special}\n")
    with pytest.raises(ValueError, match="collides"):
        load_registry(path)


# --- matcher ------------------------------------------------------------------------------------


def test_split_product_name():
    assert split_product_name("Crobat - BW51 (Team Plasma) (Prerelease)") == (
        "Crobat",
        ["Team Plasma", "Prerelease"],
    )
    assert split_product_name("Weavile - 045/217 (Dusk Ball)") == ("Weavile", ["Dusk Ball"])
    assert split_product_name("Pikachu") == ("Pikachu", [])


def _product(pid: int, number: str, name: str) -> ProductDTO:
    return ProductDTO(pid, 1, name, name, None, None, number, None)


def _card(ptcg_id: str, number: str, name: str):
    return SimpleNamespace(ptcg_card_id=ptcg_id, number=number, name=name)


def test_match_tagged_products_resolves_each_kind():
    cards = [
        _card("ex15-1", "1", "Aerodactyl"),
        _card("svp-27", "027", "Pikachu"),
        _card("sv8pt5-1", "001", "Exeggcute"),
        _card("bwp-51", "BW51", "Crobat"),
    ]
    products = [
        _product(10, "1/110", "Aerodactyl (Delta Species)"),
        _product(11, "027", "Pikachu - 027 (Prerelease)"),
        _product(12, "001/131", "Exeggcute (Poke Ball Pattern)"),
        _product(13, "BW51", "Crobat - BW51 (Team Plasma) (Prerelease)"),
        _product(14, "027", "Pikachu - 027 (Mystery Tag)"),
        _product(15, "999", "Nobody (Prerelease)"),
        _product(16, "027", "Pikachu - 027"),  # already matched by the first pass
    ]
    matches, unresolved = match_tagged_products(cards, products, {16}, REGISTRY)
    got = {m.tcgplayer_product_id: (m.ptcg_card_id, m.printing.slug if m.printing else None)
           for m in matches}
    assert got == {
        10: ("ex15-1", None),  # name tag -> the card's own product
        11: ("svp-27", "prerelease"),
        12: ("sv8pt5-1", "poke_ball_holo"),
        13: ("bwp-51", "prerelease"),  # name tag stripped, one printing tag left
    }
    reasons = {u.tcgplayer_product_id: (u.reason, u.unknown_tags) for u in unresolved}
    assert reasons == {
        14: ("unknown tag", ["Mystery Tag"]),
        15: ("no card with this number and name", []),
    }


# --- ingest ---------------------------------------------------------------------------------


def _price(pid: int, sub: str) -> PricePointDTO:
    return PricePointDTO(pid, sub, date(2026, 10, 25), None, None, None, 1.0, None)


def _variants(db, card_id: int) -> dict[str, tuple[int, bool, bool]]:
    rows = db.execute(select(CardVariant).where(CardVariant.card_id == card_id)).scalars()
    return {str(r.variant): (r.tcgplayer_product_id, r.is_special, r.is_canonical) for r in rows}


def test_derive_variants_adds_tagged_printings_beside_the_base_ones(db):
    set_row = Set(ptcg_set_id="svp", name="SV Promos")
    db.add(set_row)
    db.flush()
    pikachu = Card(ptcg_card_id="svp-27", set_id=set_row.id, number="027", name="Pikachu")
    quaquaval = Card(ptcg_card_id="svp-5", set_id=set_row.id, number="005", name="Quaquaval")
    aerodactyl = Card(ptcg_card_id="svp-1", set_id=set_row.id, number="001", name="Aerodactyl")
    db.add_all([pikachu, quaquaval, aerodactyl])
    db.flush()

    products = [
        _product(100, "027", "Pikachu - 027"),
        _product(101, "027", "Pikachu - 027 (Pokemon Center Exclusive)"),
        _product(102, "027", "Pikachu - 027 (Cosmos Holo)"),
        # Only ever released stamped: the stamped product IS the card.
        _product(200, "005", "Quaquaval - 005 (Prerelease)"),
        _product(300, "001", "Aerodactyl (Delta Species)"),
    ]
    prices = {
        100: [_price(100, "Holofoil")],
        101: [_price(101, "Holofoil")],
        102: [_price(102, "Holofoil")],
        200: [_price(200, "Holofoil")],
        300: [_price(300, "Normal"), _price(300, "Reverse Holofoil")],
    }
    _derive_variants(db, set_row, products, prices)
    db.commit()

    assert _variants(db, pikachu.id) == {
        "holofoil": (100, False, True),
        "pokemon_center": (101, True, False),
        "cosmos_holo": (102, True, False),
    }
    assert _variants(db, quaquaval.id) == {"holofoil": (200, False, True)}
    assert _variants(db, aerodactyl.id) == {
        "normal": (300, False, True),
        "reverse_holofoil": (300, False, False),
    }


def test_derive_variants_keeps_the_first_product_on_a_collision(db):
    set_row = Set(ptcg_set_id="xy1", name="XY")
    db.add(set_row)
    db.flush()
    vivillon = Card(ptcg_card_id="xy1-17", set_id=set_row.id, number="17", name="Vivillon")
    db.add(vivillon)
    db.flush()
    products = [
        _product(1, "17/146", "Vivillon (High Plains [Orange])"),
        _product(2, "17/146", "Vivillon (Meadow [Pink])"),
    ]
    prices = {1: [_price(1, "Holofoil")], 2: [_price(2, "Holofoil")]}
    _derive_variants(db, set_row, products, prices)
    db.commit()
    assert _variants(db, vivillon.id) == {"holofoil": (1, False, True)}


# --- editions: WotC subTypes and the Base Set (Shadowless) group --------------------------------


def test_registry_lists_base_set_shadowless_as_an_edition_group():
    group = REGISTRY.edition_groups[1663]
    assert group.ptcg_set_id == "base1"
    assert group.subtypes["Unlimited"] == "shadowless_normal"
    assert group.subtypes["1st Edition Holofoil"] == "first_edition_holofoil"


def test_loader_rejects_an_edition_group_mapping_to_an_unknown_variant(tmp_path):
    path = _write(
        tmp_path,
        "edition_groups:\n  - {group: 1, set: base1, subtypes: {Unlimited: shadowy}}\n",
    )
    with pytest.raises(ValueError, match="unknown"):
        load_registry(path)


def test_derive_variants_reads_wotc_edition_subtypes(db):
    """Jungle-era products price "1st Edition" / "Unlimited"; the unlimited copy is canonical."""
    set_row = Set(ptcg_set_id="base2", name="Jungle")
    db.add(set_row)
    db.flush()
    eevee = Card(ptcg_card_id="base2-51", set_id=set_row.id, number="51", name="Eevee")
    scyther = Card(ptcg_card_id="base2-10", set_id=set_row.id, number="10", name="Scyther")
    db.add_all([eevee, scyther])
    db.flush()
    products = [_product(1, "51/64", "Eevee"), _product(2, "10/64", "Scyther")]
    prices = {
        1: [_price(1, "1st Edition"), _price(1, "Unlimited")],
        2: [_price(2, "1st Edition Holofoil"), _price(2, "Unlimited Holofoil")],
    }
    _derive_variants(db, set_row, products, prices)
    db.commit()
    assert _variants(db, eevee.id) == {
        "first_edition_normal": (1, False, False),
        "unlimited_normal": (1, False, True),
    }
    assert _variants(db, scyther.id) == {
        "first_edition_holofoil": (2, False, False),
        "unlimited_holofoil": (2, False, True),
    }


def test_edition_group_adds_shadowless_and_first_edition_without_moving_canonical(db):
    set_row = Set(ptcg_set_id="base1", name="Base")
    db.add(set_row)
    db.flush()
    charizard = Card(ptcg_card_id="base1-4", set_id=set_row.id, number="4", name="Charizard")
    db.add(charizard)
    db.flush()
    # Primary group 604: the unlimited print with the shadow.
    _derive_variants(db, set_row, [_product(1, "4/102", "Charizard")], {1: [_price(1, "Holofoil")]})
    # Group 1663, Base Set (Shadowless).
    _derive_variants(
        db,
        set_row,
        [_product(2, "004/102", "Charizard")],
        {2: [_price(2, "1st Edition Holofoil"), _price(2, "Unlimited Holofoil")]},
        REGISTRY.edition_groups[1663],
    )
    db.commit()
    assert _variants(db, charizard.id) == {
        "holofoil": (1, False, True),
        "first_edition_holofoil": (2, False, False),
        "shadowless_holofoil": (2, False, False),
    }


def test_edition_group_sets_canonical_when_the_primary_group_never_matched(db):
    """Impostor Professor Oak: group 604 doesn't match it, so only 1663's printings exist."""
    set_row = Set(ptcg_set_id="base1", name="Base")
    db.add(set_row)
    db.flush()
    oak = Card(ptcg_card_id="base1-73", set_id=set_row.id, number="73", name="Impostor Oak")
    db.add(oak)
    db.flush()
    _derive_variants(
        db,
        set_row,
        [_product(1, "073/102", "Impostor Oak")],
        {1: [_price(1, "1st Edition"), _price(1, "Unlimited")]},
        REGISTRY.edition_groups[1663],
    )
    db.commit()
    assert _variants(db, oak.id) == {
        "first_edition_normal": (1, False, False),
        "shadowless_normal": (1, False, True),
    }


def test_set_only_ingest_includes_the_sets_edition_groups(db):
    db.add(Set(ptcg_set_id="base1", name="Base", tcgplayer_group_id=604))
    db.flush()
    pairs = resolve_group_set_pairs(db, None, ["base1"], lambda: [])
    assert pairs == [(604, "base1"), (1663, None)]
