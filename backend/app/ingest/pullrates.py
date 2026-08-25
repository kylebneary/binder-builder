"""Pull-rate profile YAML loader. data/pull_rates/*.yaml is the source of truth for
pull_rate_profile/pack_slot/slot_outcome/box_constraint (docs/02-data-model.md); these tables are
a cache of it, synced idempotently by `bb sync pullrates`.

Structural validation (probabilities sum to 1.0, slot repeats sum to cards_per_pack) happens in
Pydantic at parse time, with no DB access. The one rule that needs a DB session -- every `rarity`
string must match a real card in the set, else the simulator's pool is silently empty -- happens
in sync_pull_rates_to_db. Per docs/04-optimizer-spec.md, both must fail loudly rather than let a
bad profile through: caught and reported per-file rather than crashing the whole load, matching
the partial-safe ingest pattern in docs/01-architecture.md.
"""
import builtins
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BoxConstraint, Card, PackSlot, PullRateProfile, SlotOutcome
from app.models import Set as SetModel
from app.models.enums import Confidence

log = logging.getLogger(__name__)

_PROB_TOLERANCE = 1e-6


class SlotOutcomeSchema(BaseModel):
    rarity: str
    probability: float
    variant: str = "normal"
    pool_filter_json: dict | None = None


class PackSlotSchema(BaseModel):
    index: int
    label: str
    repeat: int = 1
    outcomes: list[SlotOutcomeSchema]

    @model_validator(mode="after")
    def _probabilities_sum_to_one(self) -> "PackSlotSchema":
        total = sum(o.probability for o in self.outcomes)
        if abs(total - 1.0) > _PROB_TOLERANCE:
            raise ValueError(
                f"slot {self.index} ({self.label!r}): outcome probabilities sum to "
                f"{total}, not 1.0"
            )
        return self


class BoxConstraintSchema(BaseModel):
    rarity: str
    scope: str = "box"
    min_per_box: int | None = None
    max_per_box: int | None = None
    exact_per_box: int | None = None


class PullRateProfileSchema(BaseModel):
    set: str
    name: str
    cards_per_pack: int = 10
    confidence: Confidence = Confidence.LOW
    sample_packs: int | None = None
    source_urls: list[str] = Field(default_factory=list)
    notes: str | None = None
    slots: list[PackSlotSchema]
    box_constraints: list[BoxConstraintSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def _repeats_sum_to_cards_per_pack(self) -> "PullRateProfileSchema":
        total = sum(s.repeat for s in self.slots)
        if total != self.cards_per_pack:
            raise ValueError(f"sum(slot.repeat)={total} != cards_per_pack={self.cards_per_pack}")
        return self

    def all_rarities(self) -> "builtins.set[str]":
        rarities = {o.rarity for slot in self.slots for o in slot.outcomes}
        rarities |= {c.rarity for c in self.box_constraints}
        return rarities


@dataclass(slots=True)
class LoadedProfile:
    source_file: str
    profile: PullRateProfileSchema


def load_pull_rate_profiles(directory: Path) -> dict[str, LoadedProfile]:
    """Keyed by the profile's `set:` (ptcg_set_id) field. Skips _TEMPLATE.yaml and EXAMPLE-*.yaml
    -- both explicitly illustrative, not meant to be loaded (see their own header comments)."""
    profiles: dict[str, LoadedProfile] = {}
    if not directory.exists():
        return profiles
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "_TEMPLATE.yaml" or path.name.startswith("EXAMPLE"):
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            profile = PullRateProfileSchema.model_validate(raw)
        except Exception as exc:
            log.error("%s: invalid pull-rate profile -- %s", path.name, exc)
            continue
        profiles[profile.set] = LoadedProfile(source_file=path.name, profile=profile)
    return profiles


@dataclass(slots=True)
class PullRateSyncResult:
    ptcg_set_id: str
    status: str  # "synced" | "no_set_row" | "invalid: <reason>"


def sync_pull_rates_to_db(
    db: Session, profiles: dict[str, LoadedProfile]
) -> list[PullRateSyncResult]:
    results: list[PullRateSyncResult] = []
    for ptcg_set_id, loaded in profiles.items():
        profile = loaded.profile
        set_row = db.execute(
            select(SetModel).where(SetModel.ptcg_set_id == ptcg_set_id)
        ).scalar_one_or_none()
        if set_row is None:
            results.append(PullRateSyncResult(ptcg_set_id, "no_set_row"))
            continue

        known_rarities = {
            r
            for (r,) in db.execute(
                select(Card.rarity).where(Card.set_id == set_row.id, Card.rarity.is_not(None))
            ).all()
        }
        unknown = profile.all_rarities() - known_rarities
        if unknown:
            results.append(
                PullRateSyncResult(ptcg_set_id, f"invalid: unknown rarity {sorted(unknown)!r}")
            )
            continue

        db_profile = db.execute(
            select(PullRateProfile).where(
                PullRateProfile.set_id == set_row.id, PullRateProfile.name == profile.name
            )
        ).scalar_one_or_none()
        if db_profile is None:
            db_profile = PullRateProfile(set_id=set_row.id, name=profile.name)
            db.add(db_profile)

        db_profile.cards_per_pack = profile.cards_per_pack
        db_profile.source_urls = profile.source_urls
        db_profile.sample_packs = profile.sample_packs
        db_profile.confidence = profile.confidence
        db_profile.notes = profile.notes
        db_profile.source_file = loaded.source_file
        # Replace children wholesale -- relationships are cascade="all, delete-orphan", so
        # reassigning drops the old rows and inserts the new ones on commit.
        db_profile.slots = [
            PackSlot(
                slot_index=slot.index,
                label=slot.label,
                repeat=slot.repeat,
                outcomes=[
                    SlotOutcome(
                        rarity=o.rarity,
                        probability=o.probability,
                        variant=o.variant,
                        pool_filter_json=o.pool_filter_json,
                    )
                    for o in slot.outcomes
                ],
            )
            for slot in profile.slots
        ]
        db_profile.box_constraints = [
            BoxConstraint(
                rarity=bc.rarity,
                scope=bc.scope,
                min_per_box=bc.min_per_box,
                max_per_box=bc.max_per_box,
                exact_per_box=bc.exact_per_box,
            )
            for bc in profile.box_constraints
        ]
        db.commit()
        results.append(PullRateSyncResult(ptcg_set_id, "synced"))
    return results
