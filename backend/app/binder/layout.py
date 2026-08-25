"""Binder layout engine. See docs/05-binder-spec.md.

Placements are axis-aligned rectangles on a pocket grid. A spread is a facing pair treated
as one rows x (2*cols) grid so art can cross the gutter -- which requires side-loading pages.
"""
from dataclasses import dataclass

CARD_W_MM = 63
CARD_H_MM = 88
POCKET_W_MM = 70
POCKET_H_MM = 95
DEFAULT_GUTTER_MM = 6


@dataclass(slots=True)
class Rect:
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1

    def overlaps(self, other: "Rect") -> bool:
        return not (
            self.row + self.row_span <= other.row
            or other.row + other.row_span <= self.row
            or self.col + self.col_span <= other.col
            or other.col + other.col_span <= self.col
        )


def validate_page(rects: list[Rect], rows: int, cols: int) -> list[str]:
    """Return human-readable violations. Empty list means valid."""
    errors: list[str] = []
    for r in rects:
        if r.row < 0 or r.col < 0 or r.row + r.row_span > rows or r.col + r.col_span > cols:
            errors.append(f"placement at ({r.row},{r.col}) does not fit in {rows}x{cols} grid")
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            if a.overlaps(b):
                errors.append(f"placements at ({a.row},{a.col}) and ({b.row},{b.col}) overlap")
    return errors


def auto_layout_set_order(**kwargs):
    """Fill pockets in card-number order. Build this first -- it is what most people want."""
    raise NotImplementedError  # TODO(phase-3.5)


def auto_layout_michi(**kwargs):
    """Cluster -> allocate spreads -> pick template -> assign -> score. See spec for weights.

    Colour work is CIELAB / deltaE2000, never RGB. RGB distance does not match perception
    and produces visibly wrong colour-themed pages.
    """
    raise NotImplementedError  # TODO(phase-3.8)


def score_layout(**kwargs) -> float:
    """0.30*symmetry + 0.25*colour_coherence + 0.20*hero_centrality
       + 0.15*fill_balance - 0.10*orphan_penalty"""
    raise NotImplementedError  # TODO(phase-3.8)
