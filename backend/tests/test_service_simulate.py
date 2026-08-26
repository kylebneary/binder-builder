from datetime import date
from decimal import Decimal

from app.models import (
    BoxConstraint,
    Card,
    CardVariant,
    Collection,
    Goal,
    PackSlot,
    PricePoint,
    PullRateProfile,
    SealedProduct,
    Set,
    SlotOutcome,
)
from app.models.enums import GoalType, Variant
from app.services.goals import materialize_goal_items
from app.services.simulate import (
    build_box_spec,
    build_card_pool,
    resolve_pull_rate_profile,
    sealed_unit_price,
)


def _seed(db):
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", release_date=date(2024, 11, 8))
    db.add(set_row)
    db.flush()

    pikachu = Card(
        ptcg_card_id="sv8-1",
        set_id=set_row.id,
        number="1",
        number_sort=1,
        name="Pikachu",
        rarity="Common",
    )
    charizard = Card(
        ptcg_card_id="sv8-2",
        set_id=set_row.id,
        number="2",
        number_sort=2,
        name="Charizard",
        rarity="Rare",
    )
    promo = Card(
        ptcg_card_id="sv8-3",
        set_id=set_row.id,
        number="3",
        number_sort=3,
        name="Promo Card",
        rarity="Promo",
    )
    db.add_all([pikachu, charizard, promo])
    db.flush()

    pikachu_normal = CardVariant(
        card_id=pikachu.id,
        variant=Variant.NORMAL,
        tcgplayer_product_id=1001,
        tcgplayer_sub_type_name="Normal",
        is_canonical=True,
    )
    pikachu_rh = CardVariant(
        card_id=pikachu.id,
        variant=Variant.REVERSE_HOLOFOIL,
        tcgplayer_product_id=1001,
        tcgplayer_sub_type_name="Reverse Holofoil",
        is_canonical=False,
    )
    charizard_holo = CardVariant(
        card_id=charizard.id,
        variant=Variant.HOLOFOIL,
        tcgplayer_product_id=1002,
        tcgplayer_sub_type_name="Holofoil",
        is_canonical=True,
    )
    promo_normal = CardVariant(
        card_id=promo.id,
        variant=Variant.NORMAL,
        tcgplayer_product_id=1003,
        tcgplayer_sub_type_name="Normal",
        is_canonical=True,
    )
    db.add_all([pikachu_normal, pikachu_rh, charizard_holo, promo_normal])
    db.flush()

    db.add_all(
        [
            PricePoint(
                tcgplayer_product_id=1001,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=Decimal("0.10"),
            ),
            PricePoint(
                tcgplayer_product_id=1001,
                sub_type_name="Reverse Holofoil",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=Decimal("0.19"),
            ),
            PricePoint(
                tcgplayer_product_id=1002,
                sub_type_name="Holofoil",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=Decimal("3.00"),
            ),
            PricePoint(
                tcgplayer_product_id=1003,
                sub_type_name="Normal",
                observed_on=date(2026, 8, 25),
                source="tcgcsv",
                market=Decimal("5.00"),
            ),
        ]
    )

    profile = PullRateProfile(
        set_id=set_row.id, name="Surging Sparks - standard booster", cards_per_pack=5,
        is_default=True,
    )
    db.add(profile)
    db.flush()
    db.add_all(
        [
            PackSlot(
                profile_id=profile.id,
                slot_index=1,
                label="common",
                repeat=4,
                outcomes=[SlotOutcome(rarity="Common", probability=1.0, variant="normal")],
            ),
            PackSlot(
                profile_id=profile.id,
                slot_index=2,
                label="rare",
                repeat=1,
                outcomes=[SlotOutcome(rarity="Rare", probability=1.0, variant="holofoil")],
            ),
        ]
    )

    collection = Collection(name="My Collection", is_default=True)
    db.add(collection)
    db.commit()

    goal = Goal(name="Surging Sparks master set", goal_type=GoalType.MASTER_SET, set_id=set_row.id)
    db.add(goal)
    db.commit()
    materialize_goal_items(db, goal)

    return {
        "set": set_row,
        "profile": profile,
        "collection": collection,
        "goal": goal,
        "pikachu_normal": pikachu_normal,
        "pikachu_rh": pikachu_rh,
        "charizard_holo": charizard_holo,
        "promo_normal": promo_normal,
    }


def test_build_card_pool_scopes_to_profile_rarity_variant_coverage(db):
    seeded = _seed(db)
    result = build_card_pool(
        db, seeded["set"].id, seeded["profile"], seeded["goal"].id, seeded["collection"].id
    )
    pool = result.pool

    # Pikachu-reverse_holofoil is excluded: (Common, reverse_holofoil) isn't a slot outcome and
    # there's no box_constraint on "Common" either.
    assert set(pool.variant_ids.tolist()) == {
        seeded["pikachu_normal"].id,
        seeded["charizard_holo"].id,
    }
    assert pool.rarities == ["Common", "Rare"]
    assert result.unpriced_needed_count == 0


def test_build_card_pool_tracks_uncovered_needed_cards_separately(db):
    seeded = _seed(db)
    result = build_card_pool(
        db, seeded["set"].id, seeded["profile"], seeded["goal"].id, seeded["collection"].id
    )
    # Pikachu-reverse_holofoil ($0.19, out of profile scope) + Promo Card ($5.00, rarity not in
    # the profile's vocabulary at all) -- neither can ever be produced by any sealed strategy.
    assert result.uncovered_needed_price_sum == Decimal("5.19")


def test_build_card_pool_needed_excludes_owned(db):
    from app.models import CollectionItem

    seeded = _seed(db)
    db.add(
        CollectionItem(
            collection_id=seeded["collection"].id,
            card_variant_id=seeded["charizard_holo"].id,
            quantity=1,
        )
    )
    db.commit()
    result = build_card_pool(
        db, seeded["set"].id, seeded["profile"], seeded["goal"].id, seeded["collection"].id
    )
    pool = result.pool
    charizard_pos = pool.variant_ids.tolist().index(seeded["charizard_holo"].id)
    pikachu_pos = pool.variant_ids.tolist().index(seeded["pikachu_normal"].id)
    assert not pool.needed[charizard_pos]  # owned
    assert pool.needed[pikachu_pos]  # not owned


def test_resolve_pull_rate_profile_falls_back_to_default(db):
    seeded = _seed(db)
    sealed = SealedProduct(
        set_id=seeded["set"].id,
        tcgplayer_product_id=2001,
        name="Surging Sparks Booster Box",
        packs_per_unit=36,
    )
    db.add(sealed)
    db.commit()
    resolved = resolve_pull_rate_profile(db, sealed)
    assert resolved is not None
    assert resolved.id == seeded["profile"].id


def test_resolve_pull_rate_profile_honors_explicit_override(db):
    seeded = _seed(db)
    other_profile = PullRateProfile(
        set_id=seeded["set"].id, name="Alternate config", cards_per_pack=5, is_default=False
    )
    db.add(other_profile)
    db.flush()
    sealed = SealedProduct(
        set_id=seeded["set"].id,
        tcgplayer_product_id=2002,
        name="Surging Sparks Special Box",
        packs_per_unit=36,
        pack_config_id=other_profile.id,
    )
    db.add(sealed)
    db.commit()
    resolved = resolve_pull_rate_profile(db, sealed)
    assert resolved is not None
    assert resolved.id == other_profile.id


def test_build_box_spec_returns_none_without_packs_per_unit(db):
    seeded = _seed(db)
    result = build_card_pool(
        db, seeded["set"].id, seeded["profile"], seeded["goal"].id, seeded["collection"].id
    )
    sealed = SealedProduct(
        set_id=seeded["set"].id, tcgplayer_product_id=2003, name="Loose Pack", packs_per_unit=None
    )
    db.add(sealed)
    db.commit()
    assert build_box_spec(db, sealed, result.pool, unit_price=None) is None


def test_build_box_spec_builds_pack_and_slots(db):
    seeded = _seed(db)
    result = build_card_pool(
        db, seeded["set"].id, seeded["profile"], seeded["goal"].id, seeded["collection"].id
    )
    sealed = SealedProduct(
        set_id=seeded["set"].id,
        tcgplayer_product_id=2004,
        name="Surging Sparks Booster Box",
        packs_per_unit=36,
    )
    db.add(sealed)
    db.commit()
    box = build_box_spec(db, sealed, result.pool, unit_price=Decimal("100.00"))
    assert box is not None
    assert box.packs_per_box == 36
    assert box.unit_price == 100.0
    assert box.pack.cards_per_pack == 5
    assert [s.label for s in box.pack.slots] == ["common", "rare"]
    assert box.guarantees == {}


def test_build_box_spec_maps_box_constraints_to_guarantees(db):
    seeded = _seed(db)
    bc = BoxConstraint(
        profile_id=seeded["profile"].id, rarity="Rare", scope="box", exact_per_box=3
    )
    db.add(bc)
    db.commit()
    result = build_card_pool(
        db, seeded["set"].id, seeded["profile"], seeded["goal"].id, seeded["collection"].id
    )
    sealed = SealedProduct(
        set_id=seeded["set"].id,
        tcgplayer_product_id=2005,
        name="Surging Sparks Booster Box",
        packs_per_unit=36,
    )
    db.add(sealed)
    db.commit()
    box = build_box_spec(db, sealed, result.pool, unit_price=None)
    assert box is not None
    rare_idx = result.pool.rarities.index("Rare")
    assert box.guarantees == {rare_idx: (3, 3)}


def test_sealed_unit_price_reads_normal_subtype(db):
    seeded = _seed(db)
    sealed = SealedProduct(
        set_id=seeded["set"].id,
        tcgplayer_product_id=2006,
        name="Surging Sparks Booster Box",
        packs_per_unit=36,
    )
    db.add(sealed)
    db.add(
        PricePoint(
            tcgplayer_product_id=2006,
            sub_type_name="Normal",
            observed_on=date(2026, 8, 25),
            source="tcgcsv",
            market=Decimal("119.99"),
        )
    )
    db.commit()
    assert sealed_unit_price(db, sealed) == Decimal("119.99")


def test_sealed_unit_price_returns_none_without_a_price_point(db):
    seeded = _seed(db)
    sealed = SealedProduct(
        set_id=seeded["set"].id, tcgplayer_product_id=2007, name="Unpriced Box", packs_per_unit=36
    )
    db.add(sealed)
    db.commit()
    assert sealed_unit_price(db, sealed) is None
