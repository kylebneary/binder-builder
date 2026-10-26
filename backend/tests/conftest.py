from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.db import enable_sqlite_foreign_keys
from app.models import Base
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Mirror the CREATE VIEWs in backend/migrations/versions/ -- create_all() only builds tables from
# ORM models, never views, so tests need them declared here too. Kept as literals rather than
# imported from the migrations, which are frozen snapshots and must not follow app code; the
# safety net against drift is behavioural (see
# test_service_portfolio.test_collection_holding_view_agrees_with_the_default_grouping).
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


# b7e2d5a91c04. The default roll-up of physical rows into holdings; SUM(quantity), not COUNT(*),
# because a row with no location can stand for N indistinguishable copies.
_COLLECTION_HOLDING_VIEW_SQL = """
CREATE VIEW collection_holding AS
SELECT
    collection_id,
    card_variant_id,
    condition,
    language,
    is_graded,
    grade,
    SUM(quantity) AS quantity,
    COUNT(*) AS copy_rows,
    COUNT(storage_location) AS located_copies,
    MIN(storage_location) AS first_location,
    SUM(acquired_price * quantity) AS acquired_total
FROM collection_item
GROUP BY collection_id, card_variant_id, condition, language, is_graded, grade
"""


def create_test_schema(engine) -> None:
    """Every table, both views, and SQLite's foreign keys switched on.

    The FK pragma matters: without it SQLite ignores every ondelete="CASCADE" and tests pass
    against behaviour production does not have. See app/db.py.

    create_all (not Alembic) is fine here -- tests are the documented exception in
    docs/02-data-model.md ("do not use create_all outside tests").
    """
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_CURRENT_PRICE_VIEW_SQL))
        conn.execute(text(_COLLECTION_HOLDING_VIEW_SQL))


@pytest.fixture
def db() -> Session:
    """In-memory SQLite session with the full test schema."""
    engine = create_engine("sqlite:///:memory:")
    create_test_schema(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed_catalogue(db: Session) -> SimpleNamespace:
    """A small two-set, two-era catalogue for card search, custom goals and goal layouts.

    Built to hit the awkward cases rather than the easy ones:
      * dex 25 sits beside 125 and 250, which a naive substring match on the JSON text confuses;
      * a tag-team card lists two species, and must match either but name neither;
      * one Pikachu ex has no `card_variant` at all (an unpriced chase card), so it can be
        counted but never placed;
      * the Surging Sparks Pikachu ex has a non-canonical reverse holo, and its Normal is owned.

    Returns the rows by short name so tests read as `cat.pikachu_ex_normal.id`.
    """
    from app.models import Card, CardVariant, Collection, CollectionItem, PricePoint, Set
    from app.models.enums import Variant

    base = Set(
        ptcg_set_id="base1", name="Base", series="Base", release_date=date(1999, 1, 9)
    )
    sparks = Set(
        ptcg_set_id="sv8",
        name="Surging Sparks",
        series="Scarlet & Violet",
        release_date=date(2024, 11, 8),
    )
    db.add_all([base, sparks])
    db.flush()

    def card(set_row, number, name, *, dex, types=None, subtypes=None, artist=None,
             rarity="Common", supertype="Pokémon"):
        row = Card(
            ptcg_card_id=f"{set_row.ptcg_set_id}-{number}",
            set_id=set_row.id,
            number=str(number),
            number_sort=number,
            name=name,
            supertype=supertype,
            rarity=rarity,
            artist=artist,
            types=types,
            subtypes=subtypes,
            national_pokedex_numbers=dex,
        )
        db.add(row)
        db.flush()
        return row

    product = iter(range(700000, 700100))

    def variant(card_row, kind=Variant.NORMAL, *, canonical=True, market=None):
        row = CardVariant(
            card_id=card_row.id,
            variant=kind,
            tcgplayer_product_id=next(product),
            tcgplayer_sub_type_name={
                Variant.NORMAL: "Normal",
                Variant.HOLOFOIL: "Holofoil",
                Variant.REVERSE_HOLOFOIL: "Reverse Holofoil",
            }[kind],
            is_canonical=canonical,
        )
        db.add(row)
        db.flush()
        if market is not None:
            db.add(
                PricePoint(
                    tcgplayer_product_id=row.tcgplayer_product_id,
                    sub_type_name=row.tcgplayer_sub_type_name,
                    observed_on=date(2026, 8, 25),
                    source="tcgcsv",
                    market=Decimal(market),
                )
            )
        return row

    ns = SimpleNamespace(base=base, sparks=sparks)
    ns.charizard = card(base, 4, "Charizard", dex=[6], types=["Fire"], subtypes=["Stage 2"],
                        artist="Mitsuhiro Arita", rarity="Rare Holo")
    ns.charizard_holo = variant(ns.charizard, Variant.HOLOFOIL, market="300.00")
    ns.pikachu = card(base, 58, "Pikachu", dex=[25], types=["Lightning"], subtypes=["Basic"],
                      artist="Mitsuhiro Arita")
    ns.pikachu_normal = variant(ns.pikachu, market="5.00")
    ns.pikachu_ex = card(sparks, 57, "Pikachu ex", dex=[25], types=["Lightning"],
                         subtypes=["Basic", "ex"], artist="5ban Graphics", rarity="Double Rare")
    ns.pikachu_ex_normal = variant(ns.pikachu_ex, market="3.00")
    ns.pikachu_ex_reverse = variant(
        ns.pikachu_ex, Variant.REVERSE_HOLOFOIL, canonical=False, market="8.00"
    )
    ns.electabuzz = card(sparks, 60, "Electabuzz", dex=[125], types=["Lightning"],
                         subtypes=["Basic"])
    ns.electabuzz_normal = variant(ns.electabuzz, market="0.10")
    ns.ho_oh = card(sparks, 61, "Ho-Oh", dex=[250], types=["Fire"], subtypes=["Basic"])
    ns.ho_oh_normal = variant(ns.ho_oh, market="0.25")
    ns.tag_team = card(sparks, 70, "Pikachu & Zekrom-GX", dex=[25, 644],
                       types=["Lightning"], subtypes=["Basic", "TAG TEAM", "GX"],
                       artist="Mitsuhiro Arita", rarity="Rare Holo GX")
    ns.tag_team_holo = variant(ns.tag_team, Variant.HOLOFOIL, market="12.00")
    ns.research = card(sparks, 80, "Professor's Research", dex=None, subtypes=["Supporter"],
                       supertype="Trainer", rarity="Uncommon")
    ns.research_normal = variant(ns.research)  # unpriced
    ns.pikachu_ex_sir = card(sparks, 238, "Pikachu ex", dex=[25], types=["Lightning"],
                             subtypes=["Basic", "ex"], rarity="Special Illustration Rare")

    ns.collection = Collection(name="My Collection", is_default=True)
    db.add(ns.collection)
    db.flush()
    db.add(CollectionItem(
        collection_id=ns.collection.id, card_variant_id=ns.pikachu_ex_normal.id, quantity=1
    ))
    db.commit()
    return ns


@pytest.fixture
def catalogue(db: Session) -> SimpleNamespace:
    return seed_catalogue(db)
