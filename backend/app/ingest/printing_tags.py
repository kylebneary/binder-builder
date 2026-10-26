"""Loader and classifier for data/printing_tags.yaml -- what a bracketed tag in a tcgcsv product
name means. See the YAML's header for the three kinds and why they differ.

Pure apart from reading the file once; the matcher (mapping.py) and the price ingest (prices.py)
use it, and so does the read side, for collector-facing printing labels.
"""
import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from app.models.enums import Variant


class TagKind(StrEnum):
    NAME = "name"
    PRINTING = "printing"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Printing:
    """A tagged printing: its card_variant.variant value, how to show it, and whether it belongs
    to a Master Set ("set") or only a Grand Master Set ("special")."""

    slug: str
    label: str
    scope: str

    @property
    def is_special(self) -> bool:
        return self.scope == "special"


@dataclass(frozen=True, slots=True)
class TagClass:
    kind: TagKind
    printing: Printing | None = None


@dataclass(frozen=True, slots=True)
class _Pattern:
    regex: re.Pattern[str]
    slug: str
    label: str
    scope: str


@dataclass(frozen=True, slots=True)
class PrintingRegistry:
    name_tags: frozenset[str]
    name_patterns: tuple[re.Pattern[str], ...]
    printings: dict[str, Printing]  # lowercased tag or alias -> printing
    patterns: tuple[_Pattern, ...]

    def classify(self, tag: str) -> TagClass:
        """Classify one tag (or a " + "-joined combination). Tried as written, then with a
        leading number removed, so "98 Full Art" reads as "Full Art" -- but a year-led tag like
        "2014 Champion" is matched by its pattern first, before the number could be dropped."""
        key = _norm(tag)
        found = self._lookup(key)
        if found.kind == TagKind.UNKNOWN:
            stripped = re.sub(r"^\d+\s+", "", key)
            if stripped != key:
                found = self._lookup(stripped)
        return found

    def _lookup(self, key: str) -> TagClass:
        if key in self.name_tags or any(p.match(key) for p in self.name_patterns):
            return TagClass(TagKind.NAME)
        if key in self.printings:
            return TagClass(TagKind.PRINTING, self.printings[key])
        for pattern in self.patterns:
            m = pattern.regex.match(key)
            if m is None:
                continue
            values = {k: v for k, v in m.groupdict().items() if v is not None}
            if "year" in values and len(values["year"]) == 2:
                values["year"] = f"20{values['year']}"
            label_values = {k: v.title() if k != "year" else v for k, v in values.items()}
            return TagClass(
                TagKind.PRINTING,
                Printing(
                    slug=pattern.slug.format(**values),
                    label=pattern.label.format(**label_values),
                    scope=pattern.scope,
                ),
            )
        return TagClass(TagKind.UNKNOWN)

    def label_for(self, variant: str) -> str | None:
        """The collector-facing label for a tagged-printing slug, or None for the base printings
        the Variant enum covers (the UI labels those itself)."""
        for printing in self.printings.values():
            if printing.slug == variant:
                return printing.label
        for pattern in self.patterns:
            # Recover the label by re-deriving it from the slug's own values.
            template = re.escape(pattern.slug).replace(r"\{year\}", r"(?P<year>\d{4})")
            template = template.replace(r"\{season\}", r"(?P<season>[a-z]+)")
            m = re.fullmatch(template, variant)
            if m:
                values = {k: v.title() if k != "year" else v for k, v in m.groupdict().items()}
                return pattern.label.format(**values)
        return None


def _norm(tag: str) -> str:
    return re.sub(r"\s+", " ", tag.strip().lower())


def load_registry(path: Path) -> PrintingRegistry:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base_values = {v.value for v in Variant}
    printings: dict[str, Printing] = {}
    for entry in data.get("printings") or []:
        printing = Printing(entry["slug"], entry["label"], entry["scope"])
        if printing.scope not in ("set", "special"):
            raise ValueError(
                f"{path}: printing {entry['tag']!r} has unknown scope {printing.scope!r}"
            )
        if len(printing.slug) > 32:
            raise ValueError(f"{path}: slug {printing.slug!r} exceeds card_variant.variant's 32")
        for tag in [entry["tag"], *(entry.get("aliases") or [])]:
            key = _norm(tag)
            if key in printings and printings[key] != printing:
                raise ValueError(f"{path}: tag {tag!r} is listed twice with different meanings")
            printings[key] = printing
    for printing in printings.values():
        # A slug that collides with a base variant would make "is this a stamp?" ambiguous --
        # except the two pattern slugs the enum already reserved for exactly these printings.
        reserved = ("poke_ball_holo", "master_ball_holo")
        if printing.slug in base_values and printing.slug not in reserved:
            raise ValueError(f"{path}: slug {printing.slug!r} collides with a base variant")
    return PrintingRegistry(
        name_tags=frozenset(_norm(t) for t in data.get("name_tags") or []),
        name_patterns=tuple(re.compile(p) for p in data.get("name_tag_patterns") or []),
        printings=printings,
        patterns=tuple(
            _Pattern(re.compile(e["regex"]), e["slug"], e["label"], e["scope"])
            for e in data.get("patterns") or []
        ),
    )


@lru_cache(maxsize=1)
def default_registry() -> PrintingRegistry:
    return load_registry(get_settings().printing_tags_path)


@lru_cache(maxsize=512)
def printing_label(variant: str) -> str | None:
    """Label for a tagged-printing slug, for read paths (search, goals). None for base
    printings, and None rather than an error if the registry file cannot be read -- a missing
    label degrades to the slug in the UI, which is no reason to fail a page."""
    try:
        return default_registry().label_for(variant)
    except FileNotFoundError:
        return None
