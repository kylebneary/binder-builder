"""Print export. Physical accuracy is the whole point -- a blurry or mis-scaled insert is a
wasted sheet of cardstock.

This module is pure geometry and rendering: it takes plain dataclasses and writes a file, the same
way `layout.py` stays free of the ORM. `services/binder.py` gathers the rows and calls in here.

Millimetres are the unit throughout, per docs/05-binder-spec.md -- pixels are derived at render
time and never stored.

Two decisions worth knowing before reading the code:

**Bleed means the art is drawn larger than the trim.** The spec asks for exact physical dimensions
*and* a 2 mm bleed, which are in tension: bleed only does its job (no white sliver when your cut
wanders) if ink extends past the cut line. So the *trim* size is exact -- `width_pockets x 70mm` by
`height_pockets x 95mm`, which is what the crop marks mark and what you get after cutting -- and
the image is drawn to fill trim + 2 mm on every side, i.e. scaled up by about 3%. That is ordinary
print practice. DPI is validated against the trim size, per the spec's wording, so a source that
only just clears 300 DPI is drawn at ~291 DPI once bled; `MIN_DPI_MARGIN` documents the slack.

**The caption sits outside the trim.** "A footer so cut pieces stay identifiable" cannot literally
be on the cut piece -- anything inside the trim shows in the binder. It goes under each piece,
between the crop marks and the next row, where it identifies pieces while they are still on the
sheet and is discarded with the offcut.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.binder.layout import CARD_H_MM, CARD_W_MM, POCKET_H_MM, POCKET_W_MM

# Sheet sizes in mm. Letter is 8.5x11in exactly; A4 is the ISO size.
SHEETS_MM: dict[str, tuple[float, float]] = {
    "letter": (215.9, 279.4),
    "a4": (210.0, 297.0),
}

BLEED_MM = 2.0
SHEET_MARGIN_MM = 10.0
PIECE_GAP_MM = 6.0
CROP_MARK_LEN_MM = 4.0
CROP_MARK_GAP_MM = 1.0
CAPTION_H_MM = 4.0
MIN_DPI = 300

# How much effective DPI the bleed costs: art is enlarged to cover trim + 2*BLEED_MM on each axis,
# so a piece that is exactly 300 DPI at trim prints at 300 / (1 + 2*2/width) DPI once bled.
MIN_DPI_MARGIN = "a 1-pocket insert at exactly 300 DPI prints at ~292 DPI after bleed"


class ExportError(ValueError):
    """The export cannot be produced, with a reason a user can act on."""


@dataclass(slots=True)
class InsertPiece:
    """One insert to print, at its physical trim size."""

    name: str
    image_path: str
    width_pockets: int
    height_pockets: int
    page_index: int
    row: int
    col: int

    @property
    def trim_w_mm(self) -> float:
        return self.width_pockets * POCKET_W_MM

    @property
    def trim_h_mm(self) -> float:
        return self.height_pockets * POCKET_H_MM

    @property
    def bleed_w_mm(self) -> float:
        return self.trim_w_mm + 2 * BLEED_MM

    @property
    def bleed_h_mm(self) -> float:
        return self.trim_h_mm + 2 * BLEED_MM

    @property
    def caption(self) -> str:
        """Identifies the piece while it is still on the sheet. Row/col are 0-based internally;
        shown 1-based here because it is read by a person holding scissors."""
        return f"{self.name} - p{self.page_index + 1} r{self.row + 1}c{self.col + 1}"


@dataclass(slots=True)
class PlacedPiece:
    """A piece positioned on a sheet. `x_mm`/`y_mm` are the bottom-left of the *bleed* box,
    measured from the sheet's bottom-left, which is also ReportLab's origin.

    `rotated` turns the piece 90 degrees on the sheet. A 3-pocket-wide insert is 210 mm, wider
    than the printable width of both Letter (196 mm) and A4 (190 mm), so the spec's full-page-art
    archetype is unprintable upright -- but 210 mm fits comfortably in either sheet's *height*.
    Rotation is only used when a piece does not fit upright, so ordinary inserts still come off
    the printer the way you would expect to cut them.
    """

    piece: InsertPiece
    x_mm: float
    y_mm: float
    rotated: bool = False

    @property
    def footprint_w_mm(self) -> float:
        """Width on the sheet, which is the piece's *height* when rotated."""
        return self.piece.bleed_h_mm if self.rotated else self.piece.bleed_w_mm

    @property
    def footprint_h_mm(self) -> float:
        return self.piece.bleed_w_mm if self.rotated else self.piece.bleed_h_mm

    @property
    def trim_x_mm(self) -> float:
        return self.x_mm + BLEED_MM

    @property
    def trim_y_mm(self) -> float:
        return self.y_mm + BLEED_MM


@dataclass(slots=True)
class Sheet:
    pieces: list[PlacedPiece] = field(default_factory=list)


def required_pixels(width_pockets: int, height_pockets: int, dpi: int = MIN_DPI) -> tuple[int, int]:
    """Pixel dimensions a source image needs to hit `dpi` at the target trim size."""
    w_in = width_pockets * POCKET_W_MM / 25.4
    h_in = height_pockets * POCKET_H_MM / 25.4
    # ceil: 1049.6 px is not enough for 300 DPI.
    return (int(-(-w_in * dpi // 1)), int(-(-h_in * dpi // 1)))


def effective_dpi(px_w: int, px_h: int, width_pockets: int, height_pockets: int) -> float:
    """Effective DPI of an image at the target trim size -- the *lower* of the two axes, since
    the weaker one is what shows."""
    w_in = width_pockets * POCKET_W_MM / 25.4
    h_in = height_pockets * POCKET_H_MM / 25.4
    if w_in <= 0 or h_in <= 0:
        raise ExportError("Insert size must be at least one pocket in each direction.")
    return min(px_w / w_in, px_h / h_in)


def cover_size(
    box_w: float, box_h: float, src_w: float, src_h: float
) -> tuple[float, float]:
    """Size to draw a source at so it covers a box without distortion.

    Scaled uniformly and centre-cropped, never stretched: bleed changes the box's aspect (about
    2% on a 3x1 strip), and silently squashing artwork by 2% is exactly the kind of wrongness
    you only notice once it is printed.
    """
    if src_w <= 0 or src_h <= 0:
        raise ExportError("Image has no pixel dimensions.")
    if box_w / box_h > src_w / src_h:
        return box_w, box_w * src_h / src_w
    return box_h * src_w / src_h, box_h


def pack_sheets(
    pieces: list[InsertPiece], page_size: str = "letter", *, reserve_footer_mm: float = 8.0
) -> list[Sheet]:
    """Shelf packing, first-fit-decreasing by height.

    Tall pieces first, laid left to right along a shelf; a shelf's height is set by its first
    piece. It is not optimal -- 2D bin packing is NP-hard and an optimal packer would save the
    occasional sheet -- but it is predictable, and a person cutting these out benefits more from
    pieces sitting in tidy rows than from the last 3% of paper.
    """
    if page_size not in SHEETS_MM:
        raise ExportError(f"Unknown page size {page_size!r} -- use one of: {', '.join(SHEETS_MM)}")
    sheet_w, sheet_h = SHEETS_MM[page_size]
    usable_w = sheet_w - 2 * SHEET_MARGIN_MM
    usable_h = sheet_h - 2 * SHEET_MARGIN_MM - reserve_footer_mm

    def fits(w: float, h: float) -> bool:
        return w <= usable_w and h + CAPTION_H_MM <= usable_h

    def orientation(p: InsertPiece) -> bool | None:
        """False = upright, True = rotated, None = fits neither way."""
        if fits(p.bleed_w_mm, p.bleed_h_mm):
            return False
        if fits(p.bleed_h_mm, p.bleed_w_mm):
            return True
        return None

    too_big = [p for p in pieces if orientation(p) is None]
    if too_big:
        names = ", ".join(sorted({p.name for p in too_big}))
        raise ExportError(
            f"{names} does not fit a {page_size} sheet's printable area "
            f"({usable_w:.0f}x{usable_h:.0f} mm) in either orientation. Export at a larger page "
            f"size, or place the insert across fewer pockets."
        )

    # Tallest first; ties broken by width then name so the output is deterministic.
    def sort_key(p: InsertPiece) -> tuple[float, float, str, int]:
        rot = bool(orientation(p))
        return (
            -(p.bleed_w_mm if rot else p.bleed_h_mm),
            -(p.bleed_h_mm if rot else p.bleed_w_mm),
            p.name,
            p.page_index,
        )

    ordered = sorted(pieces, key=sort_key)

    sheets: list[Sheet] = []
    sheet: Sheet | None = None
    shelf_y = 0.0  # bottom of the current shelf, measured down from the top of the usable area
    shelf_h = 0.0
    cursor_x = 0.0

    def new_sheet() -> None:
        nonlocal sheet, shelf_y, shelf_h, cursor_x
        sheet = Sheet()
        sheets.append(sheet)
        shelf_y = 0.0
        shelf_h = 0.0
        cursor_x = 0.0

    new_sheet()
    for piece in ordered:
        rotated = bool(orientation(piece))
        foot_w = piece.bleed_h_mm if rotated else piece.bleed_w_mm
        foot_h = piece.bleed_w_mm if rotated else piece.bleed_h_mm
        cell_w = foot_w + PIECE_GAP_MM
        cell_h = foot_h + CAPTION_H_MM + PIECE_GAP_MM
        if cursor_x + foot_w > usable_w:  # shelf full -> next shelf
            shelf_y += shelf_h
            shelf_h = 0.0
            cursor_x = 0.0
        # cell_h carries a trailing gap the last row does not need.
        if shelf_y + cell_h - PIECE_GAP_MM > usable_h:  # sheet full -> next sheet
            new_sheet()

        # ReportLab's origin is bottom-left; shelves grow downward from the top.
        top_of_usable = sheet_h_top(page_size, reserve_footer_mm)
        y = top_of_usable - shelf_y - foot_h
        assert sheet is not None
        sheet.pieces.append(PlacedPiece(piece, SHEET_MARGIN_MM + cursor_x, y, rotated))
        cursor_x += cell_w
        shelf_h = max(shelf_h, cell_h)

    return [s for s in sheets if s.pieces]


def sheet_h_top(page_size: str, reserve_footer_mm: float = 8.0) -> float:
    """Y of the top of the usable area, in ReportLab's bottom-left origin."""
    _, sheet_h = SHEETS_MM[page_size]
    return sheet_h - SHEET_MARGIN_MM


def export_inserts_pdf(
    pieces: list[InsertPiece],
    out_path: str | Path,
    *,
    page_size: str = "letter",
    binder_name: str = "",
) -> str:
    """Write the print deliverable: every insert at exact trim size, bled, with crop marks.

    Raises ExportError rather than writing a PDF of nothing, since an empty print job is never
    what the user meant.
    """
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    if not pieces:
        raise ExportError(
            "This binder has no insert placements to print. Add an insert to a pocket first."
        )

    sheets = pack_sheets(pieces, page_size)
    sheet_w, sheet_h = SHEETS_MM[page_size]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(out), pagesize=(sheet_w * mm, sheet_h * mm))
    pdf.setTitle(f"{binder_name} inserts" if binder_name else "Binder inserts")
    today = date.today().isoformat()

    for n, sheet in enumerate(sheets, start=1):
        for placed in sheet.pieces:
            _draw_piece(pdf, placed, mm)
        pdf.setFont("Helvetica", 7)
        pdf.setFillGray(0.35)
        footer = (
            f"{binder_name or 'Binder'} - inserts - sheet {n} of {len(sheets)} - "
            f"{page_size.upper()} - print at 100% scale, do not fit to page - {today}"
        )
        pdf.drawString(SHEET_MARGIN_MM * mm, (SHEET_MARGIN_MM / 2) * mm, footer)
        pdf.setFillGray(0)
        pdf.showPage()

    pdf.save()
    return str(out)


def _draw_piece(pdf, placed: PlacedPiece, mm: float) -> None:
    """Art (bled), crop marks at the trim, and a caption in the offcut.

    Everything is drawn in the piece's own frame with its bleed box at the local origin, so
    rotation is one transform rather than a second set of coordinate formulas.
    """
    piece = placed.piece
    pdf.saveState()
    if placed.rotated:
        # After translate+rotate, the local +x axis runs up the sheet: a local box of
        # (bleed_w x bleed_h) lands on the sheet as (bleed_h x bleed_w) at (x_mm, y_mm).
        pdf.translate((placed.x_mm + piece.bleed_h_mm) * mm, placed.y_mm * mm)
        pdf.rotate(90)
    else:
        pdf.translate(placed.x_mm * mm, placed.y_mm * mm)

    # Cover the bleed box preserving aspect, then clip. Filling it directly would stretch the art
    # by however much the bleed changes the box's aspect -- about 2% on a 3x1 strip, which is
    # small, visible, and exactly the kind of silent wrongness this export exists to avoid.
    from reportlab.lib.utils import ImageReader

    art = ImageReader(piece.image_path)
    src_w, src_h = art.getSize()
    box_w, box_h = piece.bleed_w_mm, piece.bleed_h_mm
    draw_w, draw_h = cover_size(box_w, box_h, src_w, src_h)

    pdf.saveState()
    clip = pdf.beginPath()
    clip.rect(0, 0, box_w * mm, box_h * mm)
    pdf.clipPath(clip, stroke=0, fill=0)
    pdf.drawImage(
        art,
        (box_w - draw_w) / 2 * mm,
        (box_h - draw_h) / 2 * mm,
        width=draw_w * mm,
        height=draw_h * mm,
        preserveAspectRatio=False,
        mask="auto",
    )
    pdf.restoreState()

    # Trim box, local: inset from the bleed box by the bleed on every side.
    x0, y0 = BLEED_MM, BLEED_MM
    x1, y1 = x0 + piece.trim_w_mm, y0 + piece.trim_h_mm
    pdf.setLineWidth(0.25)
    pdf.setStrokeGray(0)
    g, ln = CROP_MARK_GAP_MM, CROP_MARK_LEN_MM
    for x in (x0, x1):
        for y in (y0, y1):
            y_dir = 1 if y == y1 else -1
            x_dir = 1 if x == x1 else -1
            # Marks sit outside the trim corner, leaving a gap so they never print on the piece.
            pdf.line(x * mm, (y + y_dir * g) * mm, x * mm, (y + y_dir * (g + ln)) * mm)
            pdf.line((x + x_dir * g) * mm, y * mm, (x + x_dir * (g + ln)) * mm, y * mm)

    pdf.setFont("Helvetica", 5.5)
    pdf.setFillGray(0.4)
    caption = piece.caption + (" [rotated]" if placed.rotated else "")
    pdf.drawString(0, (-CAPTION_H_MM + 0.5) * mm, caption[:70])
    pdf.setFillGray(0)
    pdf.restoreState()



# --- spread preview PNG (3.10) -------------------------------------------------------------------


@dataclass(slots=True)
class RenderPlacement:
    """One thing to draw on a spread preview.

    `col` follows the storage convention from `layout.py`: spread coordinates (0..2*cols-1) when
    `spans_gutter`, otherwise per-page, with `page_side` saying which half of the spread it is on.
    `image_path` is always a local file -- resolving a card's CDN URL to a cached file is the
    service layer's job, so this module never reaches the network.
    """

    row: int
    col: int
    row_span: int
    col_span: int
    page_side: int  # 0 = left page, 1 = right page; ignored when spans_gutter
    kind: str = "card"
    spans_gutter: bool = False
    image_path: str | None = None
    label: str = ""
    is_owned: bool = True


def spread_column_x_mm(col: int, cols: int, gutter_mm: float) -> float:
    """Left edge of a spread column, in mm from the spread's left edge. The gutter sits between
    the last column of the left page and the first of the right."""
    return col * POCKET_W_MM + (gutter_mm if col >= cols else 0.0)


def render_spread_png(
    placements: list[RenderPlacement],
    out_path: str | Path,
    *,
    rows: int,
    cols: int,
    gutter_mm: float = 6.0,
    dpi: int = 150,
    binder_name: str = "",
    spread_index: int = 0,
) -> str:
    """Draw a facing pair at true proportions.

    150 DPI by default, not 300: this is a screen preview and a shareable image, and a 3x3 spread
    at 300 DPI is a 5000px file nobody wanted. The spec's 300 DPI floor is about the *print*
    deliverable.

    Proportions matter more than polish here -- docs/05-binder-spec.md notes that a preview which
    misstates them is worse than no preview -- so every dimension comes from the same mm geometry
    the PDF uses.
    """
    from PIL import Image, ImageDraw

    px = dpi / 25.4  # pixels per mm

    def to_px(mm_value: float) -> int:
        return round(mm_value * px)

    margin_mm = 8.0
    caption_mm = 7.0
    spread_w_mm = 2 * cols * POCKET_W_MM + gutter_mm
    spread_h_mm = rows * POCKET_H_MM
    img_w = to_px(spread_w_mm + 2 * margin_mm)
    img_h = to_px(spread_h_mm + 2 * margin_mm + caption_mm)

    canvas = Image.new("RGB", (img_w, img_h), (247, 246, 243))
    draw = ImageDraw.Draw(canvas)
    ox, oy = to_px(margin_mm), to_px(margin_mm)

    # Gutter band first, so pocket outlines sit on top of it.
    if gutter_mm > 0:
        gx0 = ox + to_px(cols * POCKET_W_MM)
        draw.rectangle(
            [gx0, oy, gx0 + to_px(gutter_mm), oy + to_px(spread_h_mm)],
            fill=(226, 223, 216),
        )

    # Empty pocket outlines across both pages.
    for r in range(rows):
        for c in range(2 * cols):
            x0 = ox + to_px(spread_column_x_mm(c, cols, gutter_mm))
            y0 = oy + to_px(r * POCKET_H_MM)
            draw.rectangle(
                [x0, y0, x0 + to_px(POCKET_W_MM), y0 + to_px(POCKET_H_MM)],
                outline=(206, 202, 194),
                width=max(1, to_px(0.4)),
            )

    for p in sorted(placements, key=lambda q: (q.row, q.col)):
        start_col = p.col if p.spans_gutter else p.col + p.page_side * cols
        end_col = start_col + p.col_span - 1
        x0_mm = spread_column_x_mm(start_col, cols, gutter_mm)
        x1_mm = spread_column_x_mm(end_col, cols, gutter_mm) + POCKET_W_MM
        y0_mm = p.row * POCKET_H_MM
        y1_mm = y0_mm + p.row_span * POCKET_H_MM
        box = (ox + to_px(x0_mm), oy + to_px(y0_mm), ox + to_px(x1_mm), oy + to_px(y1_mm))

        if p.kind == "card":
            # A card is 63x88 in a 70x95 pocket; drawing it pocket-sized would overstate it.
            inset_x = to_px((POCKET_W_MM - CARD_W_MM) / 2)
            inset_y = to_px((POCKET_H_MM - CARD_H_MM) / 2)
            box = (box[0] + inset_x, box[1] + inset_y, box[2] - inset_x, box[3] - inset_y)

        _draw_art(canvas, draw, box, p)

    caption = f"{binder_name or 'Binder'} - spread {spread_index + 1} (pages "
    caption += f"{2 * spread_index + 1}-{2 * spread_index + 2})"
    draw.text((ox, img_h - to_px(caption_mm)), caption, fill=(110, 106, 98))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, format="PNG")
    return str(out)


def _draw_art(canvas, draw, box: tuple[int, int, int, int], p: RenderPlacement) -> None:
    """Art scaled to cover its box, or a labelled placeholder when there is none."""
    from PIL import Image

    w, h = box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0:
        return

    if p.image_path and Path(p.image_path).exists():
        try:
            with Image.open(p.image_path) as art:
                art = art.convert("RGB")
                # Cover, then centre-crop: letterboxing a card would misstate its proportions.
                scale = max(w / art.width, h / art.height)
                resized = art.resize(
                    (max(1, int(art.width * scale)), max(1, int(art.height * scale))),
                    Image.LANCZOS,
                )
                left = (resized.width - w) // 2
                top = (resized.height - h) // 2
                canvas.paste(resized.crop((left, top, left + w, top + h)), (box[0], box[1]))
        except OSError:
            # A cache file that is present but corrupt should not sink the whole preview.
            draw.rectangle(box, fill=(232, 229, 222))
    else:
        draw.rectangle(box, fill=(232, 229, 222))
        if p.label:
            draw.text((box[0] + 4, box[1] + 4), p.label[:24], fill=(120, 116, 108))

    outline = (198, 84, 72) if not p.is_owned else (60, 58, 54)
    draw.rectangle(box, outline=outline, width=max(1, w // 90))
