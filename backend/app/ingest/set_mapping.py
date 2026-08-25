"""Map pokemontcg.io sets to tcgcsv groupIds -- phase 1.5.

There is no shared key (see docs/03-data-sources.md "Joining pokemontcg.io to tcgcsv"). This
module fuzzy-matches by normalized name + release-date proximity, seeding `data/set_map.yaml`,
which is then the curated source of truth (hand-corrected residue lives there, not here) --
`bb sync setmap` is the idempotent loader that writes it into `Set.tcgplayer_group_id`.
"""
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.base import SetDTO
from app.models import Set

log = logging.getLogger(__name__)

# tcgcsv group names are usually prefixed with an era/set code, e.g. "SV08: Surging Sparks",
# "ME06: Delta Reign", "ME: 30th Celebration". pokemontcg.io's name is just "Surging Sparks".
_CODE_PREFIX = re.compile(r"^[A-Z0-9]{1,6}:\s*")

# Presale/listing dates on tcgcsv can run weeks to months ahead of pokemontcg.io's release date.
_DATE_TOLERANCE_DAYS = 120

# Below this combined score, don't guess -- report for manual review instead.
_MATCH_THRESHOLD = 0.55
# Two candidates within this score of each other are too close to call automatically.
_AMBIGUITY_MARGIN = 0.05


@dataclass(slots=True)
class SetMatchResult:
    ptcg_set_id: str
    tcgplayer_group_id: int | None
    confidence: float
    reason: str


def normalize_group_name(raw: str) -> str:
    """Strip tcgcsv's leading era/set code and normalize for comparison."""
    s = _CODE_PREFIX.sub("", raw).lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_set_name(raw: str) -> str:
    s = raw.lower()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_published_on(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _date_score(a: date | None, b: date | None) -> float:
    if a is None or b is None:
        return 0.5  # neutral -- neither confirms nor denies a name match
    delta_days = abs((a - b).days)
    if delta_days > _DATE_TOLERANCE_DAYS:
        return 0.0
    return 1.0 - (delta_days / _DATE_TOLERANCE_DAYS)


def match_sets(
    ptcg_sets: list[SetDTO], tcgcsv_groups: list[dict]
) -> list[SetMatchResult]:
    """One `SetMatchResult` per ptcg set (never per group), so every set is reported --
    including the ones with no confident tcgcsv counterpart -- rather than silently dropped.
    """
    candidates = [
        (g, normalize_group_name(g["name"]), _parse_published_on(g.get("publishedOn")))
        for g in tcgcsv_groups
    ]

    results: list[SetMatchResult] = []
    for ptcg_set in ptcg_sets:
        norm_name = normalize_set_name(ptcg_set.name)
        scored = []
        for group, group_norm_name, published_on in candidates:
            name_sim = _name_similarity(norm_name, group_norm_name)
            combined = 0.7 * name_sim + 0.3 * _date_score(ptcg_set.release_date, published_on)
            scored.append((combined, name_sim, group))
        scored.sort(key=lambda t: t[0], reverse=True)

        if not scored or scored[0][0] < _MATCH_THRESHOLD or scored[0][1] < 0.5:
            results.append(
                SetMatchResult(ptcg_set.ptcg_set_id, None, 0.0, "no confident tcgcsv match")
            )
            continue

        if len(scored) > 1 and (scored[0][0] - scored[1][0]) < _AMBIGUITY_MARGIN:
            results.append(
                SetMatchResult(
                    ptcg_set.ptcg_set_id,
                    None,
                    0.5,
                    f"ambiguous: top candidates {scored[0][2]['groupId']} and "
                    f"{scored[1][2]['groupId']} score within {_AMBIGUITY_MARGIN}",
                )
            )
            continue

        results.append(
            SetMatchResult(ptcg_set.ptcg_set_id, scored[0][2]["groupId"], 1.0, "matched")
        )
    return results


_HEADER = (
    "# ptcg_set_id -> tcgcsv groupId. Seeded by scripts/build_set_map.py (fuzzy match on name\n"
    "# + release date); this file is the source of truth from there -- hand-correct entries\n"
    "# here directly, re-running the script only ever adds new keys, never overwrites existing\n"
    "# ones. `bb sync setmap` loads this into Set.tcgplayer_group_id.\n"
)


def load_set_map(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): int(v) for k, v in data.items()}


def merge_set_map(path: Path, new_entries: dict[str, int]) -> dict[str, int]:
    """Add only keys not already present -- an existing (possibly hand-corrected) entry is
    never overwritten by a re-run of the fuzzy matcher."""
    existing = load_set_map(path)
    merged = dict(existing)
    added = {k: v for k, v in new_entries.items() if k not in existing}
    merged.update(added)
    if added:
        lines = [_HEADER]
        for ptcg_set_id in sorted(merged):
            lines.append(f"{ptcg_set_id}: {merged[ptcg_set_id]}\n")
        path.write_text("".join(lines))
        log.info("Added %d new set_map entries to %s", len(added), path)
    return merged


@dataclass(slots=True)
class SetMapSyncResult:
    ptcg_set_id: str
    tcgplayer_group_id: int
    status: str  # "linked" | "updated" | "unchanged" | "no_set_row"


def sync_set_map_to_db(db: Session, mapping: dict[str, int]) -> list[SetMapSyncResult]:
    """Idempotently write `mapping` (ptcg_set_id -> tcgcsv groupId) into `Set.tcgplayer_group_id`.

    data/set_map.yaml is the source of truth; the DB column is a cache of it (same pattern as
    the pull-rate YAML in docs/02-data-model.md). A set with no matching row yet is reported,
    not silently skipped -- it needs `bb ingest cards --set <id>` first.
    """
    results: list[SetMapSyncResult] = []
    for ptcg_set_id, group_id in mapping.items():
        set_row = db.execute(
            select(Set).where(Set.ptcg_set_id == ptcg_set_id)
        ).scalar_one_or_none()
        if set_row is None:
            results.append(SetMapSyncResult(ptcg_set_id, group_id, "no_set_row"))
            continue
        if set_row.tcgplayer_group_id == group_id:
            results.append(SetMapSyncResult(ptcg_set_id, group_id, "unchanged"))
            continue
        was_mapped = set_row.tcgplayer_group_id is not None
        if was_mapped:
            log.warning(
                "Set %s: tcgplayer_group_id changing %s -> %s per set_map.yaml",
                ptcg_set_id,
                set_row.tcgplayer_group_id,
                group_id,
            )
        set_row.tcgplayer_group_id = group_id
        results.append(
            SetMapSyncResult(ptcg_set_id, group_id, "updated" if was_mapped else "linked")
        )
    db.commit()
    return results
