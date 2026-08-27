from datetime import date
from decimal import Decimal

from app.models import (
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
from app.services.simulation_runs import run_and_cache, run_search_and_cache, run_sensitivity
from app.sim.optimizer import Objective
from app.sim.types import CostParams, Strategy


def _seed(db):
    set_row = Set(ptcg_set_id="sv8", name="Surging Sparks", release_date=date(2024, 11, 8))
    db.add(set_row)
    db.flush()

    rare = Card(
        ptcg_card_id="sv8-1", set_id=set_row.id, number="1", number_sort=1, name="Charizard",
        rarity="Rare",
    )
    db.add(rare)
    db.flush()
    rare_holo = CardVariant(
        card_id=rare.id, variant=Variant.HOLOFOIL, tcgplayer_product_id=1001,
        tcgplayer_sub_type_name="Holofoil", is_canonical=True,
    )
    db.add(rare_holo)
    db.flush()
    db.add(
        PricePoint(
            tcgplayer_product_id=1001, sub_type_name="Holofoil", observed_on=date(2026, 8, 25),
            source="tcgcsv", market=Decimal("20.00"), low=Decimal("15.00"), high=Decimal("30.00"),
        )
    )

    profile = PullRateProfile(
        set_id=set_row.id, name="Surging Sparks - standard booster", cards_per_pack=1,
        is_default=True,
    )
    db.add(profile)
    db.flush()
    db.add(
        PackSlot(
            profile_id=profile.id, slot_index=1, label="rare", repeat=1,
            outcomes=[SlotOutcome(rarity="Rare", probability=1.0, variant="holofoil")],
        )
    )

    sealed = SealedProduct(
        set_id=set_row.id, tcgplayer_product_id=2001, name="Booster Box", packs_per_unit=4,
    )
    db.add(sealed)
    db.add(
        PricePoint(
            tcgplayer_product_id=2001, sub_type_name="Normal", observed_on=date(2026, 8, 25),
            source="tcgcsv", market=Decimal("5.00"),
        )
    )

    collection = Collection(name="My Collection", is_default=True)
    db.add(collection)
    db.commit()

    goal = Goal(name="Surging Sparks master set", goal_type=GoalType.MASTER_SET, set_id=set_row.id)
    db.add(goal)
    db.commit()
    materialize_goal_items(db, goal)

    return {"set": set_row, "goal": goal, "sealed": sealed, "profile": profile}


def test_run_and_cache_persists_a_simulation_run(db):
    seeded = _seed(db)
    run = run_and_cache(
        db, seeded["goal"].id, Strategy(units={seeded["sealed"].id: 1}), CostParams(),
        n_trials=1000, seed=0,
    )
    assert run.id is not None
    assert run.goal_id == seeded["goal"].id
    assert run.n_trials == 1000
    assert "mean" in run.results_json


def test_run_and_cache_hits_cache_on_identical_request(db):
    seeded = _seed(db)
    strategy = Strategy(units={seeded["sealed"].id: 1})
    run1 = run_and_cache(db, seeded["goal"].id, strategy, CostParams(), n_trials=1000, seed=0)
    run2 = run_and_cache(db, seeded["goal"].id, strategy, CostParams(), n_trials=1000, seed=0)
    assert run1.id == run2.id


def test_run_and_cache_misses_on_changed_params(db):
    seeded = _seed(db)
    strategy = Strategy(units={seeded["sealed"].id: 1})
    run1 = run_and_cache(db, seeded["goal"].id, strategy, CostParams(), n_trials=1000, seed=0)
    run2 = run_and_cache(
        db, seeded["goal"].id, strategy, CostParams(liquidation_rate=0.9), n_trials=1000, seed=0
    )
    assert run1.id != run2.id


def test_run_search_and_cache_includes_baseline_and_ranks_results(db):
    seeded = _seed(db)
    result = run_search_and_cache(
        db, seeded["goal"].id, Objective.MIN_EXPECTED_COST, CostParams(), n_trials=1000, seed=0
    )
    assert not result.unsimulatable
    strategies = [tuple(r.strategy_json.items()) for r in result.runs]
    assert () in strategies  # singles-only baseline serializes to an empty dict
    means = [r.results_json["mean"] for r in result.runs]
    assert means == sorted(means)


def test_run_search_and_cache_reports_unsimulatable_products(db):
    seeded = _seed(db)
    unpriced_no_packs = SealedProduct(
        set_id=seeded["set"].id, tcgplayer_product_id=2002, name="Loose Pack",
        packs_per_unit=None,
    )
    db.add(unpriced_no_packs)
    db.commit()
    result = run_search_and_cache(
        db, seeded["goal"].id, Objective.MIN_EXPECTED_COST, CostParams(), n_trials=1000, seed=0
    )
    assert any(u["sealed_product_id"] == unpriced_no_packs.id for u in result.unsimulatable)


def test_run_sensitivity_includes_price_basis_factor(db):
    seeded = _seed(db)
    result = run_sensitivity(
        db, seeded["goal"].id, Strategy(units={seeded["sealed"].id: 1}), CostParams(),
        n_trials=1000, seed=0,
    )
    names = [f["name"] for f in result["factors"]]
    assert "price basis (low vs. high)" in names
    assert isinstance(result["robust"], bool)
