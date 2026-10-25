"""Michi spread templates: the hand-designed page archetypes the auto-layout picks from
(roadmap 3.7).

A template is a named grid of typed slots covering a whole spread -- rows x (2*cols) -- in the
spread coordinates `layout.py` documents. It is data, not code, so a collector can add an
archetype by writing YAML in `data/binder_templates/` without touching Python.

Every file is validated on load: slots in bounds, no self-overlap, at most one hero, and
gutter-spanning slots that actually straddle the gutter. A template that overlaps itself would
produce a layout the placement service then rejects, which is a confusing way to find out about a
typo in a YAML file.
"""
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.binder.layout import Rect

SLOT_KINDS = ("hero", "card", "insert", "empty")
# Slots that hold a card from the pool. The hero is one of them -- it is a card, just the one the
# spread is built around -- so a template's card capacity includes it.
CARD_KINDS = ("hero", "card")


class TemplateError(ValueError):
    """A template file is malformed, with the file named."""


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    kind: str = "card"
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    spans_gutter: bool = False

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in SLOT_KINDS:
            raise ValueError(f"kind must be one of {', '.join(SLOT_KINDS)}, got {v!r}")
        return v

    @property
    def rect(self) -> Rect:
        return Rect(self.row, self.col, self.row_span, self.col_span)

    @property
    def holds_card(self) -> bool:
        return self.kind in CARD_KINDS


class SpreadTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    rows: int = Field(ge=1)
    cols: int = Field(ge=1)
    slots: list[Slot]
    requires_side_loading: bool = False
    # Optional in the file. Always derived; a declared value that disagrees is an error rather
    # than something to silently prefer, because it means the file and its slots have drifted.
    card_slots: int | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> SpreadTemplate:
        spread_cols = 2 * self.cols
        problems: list[str] = []

        for slot in self.slots:
            if slot.row + slot.row_span > self.rows:
                problems.append(f"slot at r{slot.row}c{slot.col} runs past the last row")
            if slot.col + slot.col_span > spread_cols:
                problems.append(
                    f"slot at r{slot.row}c{slot.col} runs past the spread's last column"
                )
            if slot.spans_gutter:
                if not (slot.col < self.cols < slot.col + slot.col_span):
                    problems.append(
                        f"slot at r{slot.row}c{slot.col} is flagged spans_gutter but does not "
                        f"cross column {self.cols}"
                    )
                if not self.requires_side_loading:
                    problems.append(
                        f"slot at r{slot.row}c{slot.col} spans the gutter, so the template must "
                        "set requires_side_loading: true"
                    )

        for i, a in enumerate(self.slots):
            for b in self.slots[i + 1 :]:
                if a.rect.overlaps(b.rect):
                    problems.append(
                        f"slots at r{a.row}c{a.col} and r{b.row}c{b.col} overlap"
                    )

        heroes = [s for s in self.slots if s.kind == "hero"]
        if len(heroes) > 1:
            problems.append(f"{len(heroes)} hero slots; a spread is built around exactly one")

        derived = sum(1 for s in self.slots if s.holds_card)
        if self.card_slots is not None and self.card_slots != derived:
            problems.append(
                f"card_slots says {self.card_slots} but the slots hold {derived} cards "
                f"(hero slots count as card slots)"
            )
        if derived == 0:
            problems.append("no card or hero slots, so nothing from the pool could be placed")

        if problems:
            raise ValueError("; ".join(problems))
        self.card_slots = derived
        return self

    @property
    def hero(self) -> Slot | None:
        return next((s for s in self.slots if s.kind == "hero"), None)

    @property
    def card_capacity(self) -> int:
        return sum(1 for s in self.slots if s.holds_card)

    def card_slots_in_reading_order(self) -> list[Slot]:
        """Card slots top-to-bottom, left-to-right, with the hero first.

        The hero leads because assignment gives it the group's standout card; the rest follow the
        order a person's eye takes across a spread.
        """
        rest = sorted(
            (s for s in self.slots if s.kind == "card"), key=lambda s: (s.row, s.col)
        )
        hero = self.hero
        return ([hero] if hero else []) + rest


def load_template(path: str | Path) -> SpreadTemplate:
    file_path = Path(path)
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TemplateError(f"{file_path.name}: could not read as YAML -- {exc}") from exc
    if not isinstance(raw, dict):
        raise TemplateError(f"{file_path.name}: expected a mapping at the top level")
    try:
        return SpreadTemplate.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, or our own ValueError
        raise TemplateError(f"{file_path.name}: {exc}") from exc


def load_templates(directory: str | Path) -> list[SpreadTemplate]:
    """Every template in a directory, sorted by name. Raises on the first malformed file rather
    than quietly shipping a smaller library than the user thinks they have."""
    d = Path(directory)
    if not d.exists():
        return []
    return sorted(
        (load_template(p) for p in sorted(d.glob("*.yaml"))), key=lambda t: t.name
    )


@lru_cache
def default_templates() -> tuple[SpreadTemplate, ...]:
    """The configured library. Cached: these are read once and reused across a whole layout run."""
    from app.config import get_settings

    return tuple(load_templates(get_settings().templates_dir))


def pick_template(
    templates: Iterable[SpreadTemplate], group_size: int, *, is_side_loading: bool
) -> SpreadTemplate | None:
    """The template whose card capacity best fits `group_size`.

    Prefers a template that holds the group exactly, then the smallest that holds all of it, and
    only then the largest that does not -- overflowing a group across two spreads costs the orphan
    penalty in the score, so a template that fits is worth more than a prettier one that does not.
    Templates needing side-loading are excluded for a top-loading binder, which is a hard physical
    constraint rather than a preference.
    """
    usable = [t for t in templates if is_side_loading or not t.requires_side_loading]
    if not usable:
        return None
    fits = [t for t in usable if t.card_capacity >= group_size]
    if fits:
        return min(fits, key=lambda t: (t.card_capacity - group_size, t.name))
    return max(usable, key=lambda t: (t.card_capacity, t.name))
