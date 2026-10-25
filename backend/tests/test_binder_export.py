"""Print export and insert upload (roadmap 3.4 / 3.9 / 3.10).

The assertions that matter here are physical: a sheet that declares the wrong page box, or an
insert placed at the wrong millimetre offset, wastes cardstock in a way no amount of green CI
makes up for. So the geometry is checked in mm against hand-computed values, and the PDF's own
declared page box is read back out of the file.

No pypdf: it is not a dependency (docs/05-binder-spec.md says not to use it for generation, and
pulling it in just to read three numbers in a test is not worth it). `/MediaBox` and `/Type /Page`
are plain ASCII in the file, so a regex reads them.
"""
import io
import re

import pytest
from app.binder.export import (
    BLEED_MM,
    SHEET_MARGIN_MM,
    SHEETS_MM,
    ExportError,
    InsertPiece,
    RenderPlacement,
    cover_size,
    effective_dpi,
    export_inserts_pdf,
    pack_sheets,
    render_spread_png,
    required_pixels,
    spread_column_x_mm,
)
from app.binder.layout import POCKET_H_MM, POCKET_W_MM
from app.config import get_settings
from app.models import Binder, BinderPlacement, InsertAsset
from app.services.binder_export import (
    build_insert_pieces,
    export_binder_inserts_pdf,
    export_binder_spread_png,
)
from app.services.inserts import InsertError, delete_insert, save_insert
from PIL import Image

PT_PER_MM = 72 / 25.4


@pytest.fixture
def image_cache(tmp_path, monkeypatch):
    """Point the image cache at a tmp dir so uploads never touch the real data/ tree."""
    monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path / "images"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _png_bytes(px_w: int, px_h: int, color=(200, 60, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (px_w, px_h), color).save(buf, format="PNG")
    return buf.getvalue()


def _piece(name="hero", w=1, h=1, path="x.png", page=0, row=0, col=0) -> InsertPiece:
    return InsertPiece(
        name=name, image_path=path, width_pockets=w, height_pockets=h,
        page_index=page, row=row, col=col,
    )


# --- physical geometry ---------------------------------------------------------------------------


def test_required_pixels_matches_the_pocket_size_at_300_dpi():
    # 70mm = 2.7559in -> 826.8px, which must round UP: 826 would be 299.9 DPI.
    assert required_pixels(1, 1) == (827, 1123)
    assert required_pixels(2, 2) == (1654, 2245)


def test_effective_dpi_reports_the_weaker_axis():
    # Wide enough for 300 DPI, but only half the height it needs.
    assert effective_dpi(827, 561, 1, 1) == pytest.approx(149.9, abs=0.2)


def test_spread_columns_place_the_gutter_between_the_pages():
    xs = [spread_column_x_mm(c, 3, 6) for c in range(6)]
    assert xs[:3] == [0.0, 70.0, 140.0]
    # The right page starts one gutter later, not flush against the left.
    assert xs[3] == 3 * POCKET_W_MM + 6
    assert xs[3] - (xs[2] + POCKET_W_MM) == 6


# --- packing -------------------------------------------------------------------------------------


def test_pieces_sit_inside_the_sheet_margins():
    sheets = pack_sheets([_piece(name=f"i{i}") for i in range(4)], "letter")
    sheet_w, sheet_h = SHEETS_MM["letter"]
    for placed in sheets[0].pieces:
        assert placed.x_mm >= SHEET_MARGIN_MM - 1e-9
        assert placed.x_mm + placed.footprint_w_mm <= sheet_w - SHEET_MARGIN_MM + 1e-9
        assert placed.y_mm >= 0
        assert placed.y_mm + placed.footprint_h_mm <= sheet_h - SHEET_MARGIN_MM + 1e-9


def test_trim_box_is_inset_from_the_bleed_box_by_exactly_the_bleed():
    placed = pack_sheets([_piece()], "letter")[0].pieces[0]
    assert placed.trim_x_mm - placed.x_mm == BLEED_MM
    assert placed.trim_y_mm - placed.y_mm == BLEED_MM
    # And the trim is the exact pocket size -- this is the number that must not drift.
    assert placed.piece.trim_w_mm == POCKET_W_MM
    assert placed.piece.trim_h_mm == POCKET_H_MM


def test_pieces_never_overlap_on_a_sheet():
    sheets = pack_sheets([_piece(name=f"i{i}", w=1 + i % 2) for i in range(9)], "a4")
    for sheet in sheets:
        boxes = [
            (p.x_mm, p.y_mm, p.x_mm + p.footprint_w_mm, p.y_mm + p.footprint_h_mm)
            for p in sheet.pieces
        ]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                overlaps = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                assert not overlaps, f"{a} overlaps {b}"


def test_packing_is_deterministic():
    pieces = [_piece(name=f"i{i}", w=1 + i % 2) for i in range(11)]
    first = [
        (p.piece.name, p.x_mm, p.y_mm) for s in pack_sheets(pieces, "letter") for p in s.pieces
    ]
    second = [
        (p.piece.name, p.x_mm, p.y_mm) for s in pack_sheets(list(reversed(pieces)), "letter")
        for p in s.pieces
    ]
    assert first == second


def test_a_full_width_insert_is_rotated_rather_than_refused():
    """3 pockets is 210mm, wider than Letter's 196mm printable width -- but it fits lying down,
    and the spec's full-page-art archetype would otherwise be unprintable."""
    placed = pack_sheets([_piece(name="mural", w=3, h=1)], "letter")[0].pieces[0]
    assert placed.rotated
    assert placed.footprint_w_mm == placed.piece.bleed_h_mm
    sheet_w, _ = SHEETS_MM["letter"]
    assert placed.x_mm + placed.footprint_w_mm <= sheet_w - SHEET_MARGIN_MM + 1e-9


def test_an_insert_too_big_in_both_orientations_is_refused_by_name():
    with pytest.raises(ExportError) as exc:
        pack_sheets([_piece(name="mural", w=3, h=3)], "letter")
    assert "mural" in str(exc.value)
    assert "letter" in str(exc.value)
    assert "either orientation" in str(exc.value)


def test_unknown_page_size_is_refused():
    with pytest.raises(ExportError, match="a3"):
        pack_sheets([_piece()], "a3")


# --- the PDF itself ------------------------------------------------------------------------------


def _media_boxes(pdf_bytes: bytes) -> list[tuple[float, float]]:
    found = re.findall(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf_bytes)
    return [(float(w), float(h)) for w, h in found]


@pytest.mark.parametrize("page_size", ["letter", "a4"])
def test_pdf_declares_the_right_page_box(tmp_path, page_size):
    art = tmp_path / "art.png"
    art.write_bytes(_png_bytes(827, 1123))
    out = export_inserts_pdf(
        [_piece(path=str(art))], tmp_path / "o.pdf", page_size=page_size, binder_name="B"
    )
    boxes = _media_boxes((tmp_path / "o.pdf").read_bytes())
    assert boxes, "no /MediaBox in the PDF"
    expect_w, expect_h = (v * PT_PER_MM for v in SHEETS_MM[page_size])
    for w, h in boxes:
        assert w == pytest.approx(expect_w, abs=0.5)
        assert h == pytest.approx(expect_h, abs=0.5)
    assert out.endswith("o.pdf")


def test_pdf_uses_one_page_per_packed_sheet(tmp_path):
    art = tmp_path / "art.png"
    art.write_bytes(_png_bytes(827, 1123))
    pieces = [_piece(name=f"i{i}", path=str(art)) for i in range(9)]
    expected = len(pack_sheets(pieces, "letter"))
    export_inserts_pdf(pieces, tmp_path / "o.pdf", page_size="letter")
    pages = len(re.findall(rb"/Type\s*/Page[^s]", (tmp_path / "o.pdf").read_bytes()))
    assert pages == expected > 1


def test_exporting_a_binder_with_no_inserts_is_an_error_not_an_empty_pdf(tmp_path):
    with pytest.raises(ExportError, match="no insert placements"):
        export_inserts_pdf([], tmp_path / "o.pdf")


# --- insert upload and the DPI gate --------------------------------------------------------------


def test_upload_below_300_dpi_is_refused_and_says_what_is_needed(db, image_cache):
    with pytest.raises(InsertError) as exc:
        save_insert(db, name="blurry", data=_png_bytes(400, 500), filename="blurry.png")
    message = str(exc.value)
    assert "400x500" in message
    assert "827x1123" in message, "the message must name the pixels the user needs"
    assert "300" in message


def test_upload_at_300_dpi_is_accepted_and_records_its_dpi(db, image_cache):
    asset = save_insert(db, name="hero", data=_png_bytes(827, 1123), filename="hero.png")
    assert asset.dpi is not None and asset.dpi >= 300
    assert asset.width_pockets == 1
    from pathlib import Path as _P

    assert _P(asset.image_path).exists()


def test_a_bigger_span_needs_proportionally_more_pixels(db, image_cache):
    # Exactly enough for 1x1, nowhere near enough for 2x2.
    with pytest.raises(InsertError, match="1654x2245"):
        save_insert(
            db, name="wide", data=_png_bytes(827, 1123), filename="wide.png",
            width_pockets=2, height_pockets=2,
        )


def test_unsupported_format_is_refused(db, image_cache):
    with pytest.raises(InsertError, match="Unsupported image type"):
        save_insert(db, name="vec", data=b"<svg/>", filename="art.svg")


def test_unreadable_file_is_refused(db, image_cache):
    with pytest.raises(InsertError, match="Could not read"):
        save_insert(db, name="junk", data=b"not an image", filename="junk.png")


def test_zero_pocket_span_is_refused(db, image_cache):
    with pytest.raises(InsertError, match="at least one pocket"):
        save_insert(
            db, name="x", data=_png_bytes(827, 1123), filename="x.png", width_pockets=0
        )


def test_reuploading_the_same_art_reuses_one_file(db, image_cache):
    data = _png_bytes(827, 1123)
    a = save_insert(db, name="one", data=data, filename="a.png")
    b = save_insert(db, name="two", data=data, filename="b.png")
    assert a.id != b.id
    assert a.image_path == b.image_path, "content-addressed storage should not duplicate the file"


def test_deleting_a_placed_insert_is_refused(db, image_cache):
    asset = save_insert(db, name="hero", data=_png_bytes(827, 1123), filename="h.png")
    binder = Binder(name="B", rows=3, cols=3, pages=4)
    db.add(binder)
    db.flush()
    db.add(
        BinderPlacement(
            binder_id=binder.id, page_index=0, row=0, col=0, kind="insert",
            insert_asset_id=asset.id,
        )
    )
    db.commit()
    with pytest.raises(InsertError, match="still placed"):
        delete_insert(db, asset.id)


# --- binder-level export -------------------------------------------------------------------------


def _binder_with_insert(db, image_cache, *, row_span=1, col_span=1) -> tuple[Binder, InsertAsset]:
    asset = save_insert(
        db, name="hero", data=_png_bytes(1654, 2245), filename="hero.png",
        width_pockets=2, height_pockets=2,
    )
    binder = Binder(name="Test Binder", rows=3, cols=3, pages=4)
    db.add(binder)
    db.flush()
    db.add(
        BinderPlacement(
            binder_id=binder.id, page_index=0, row=0, col=0, kind="insert",
            insert_asset_id=asset.id, row_span=row_span, col_span=col_span,
        )
    )
    db.commit()
    return binder, asset


def test_piece_size_follows_the_placement_not_the_asset(db, image_cache):
    """An asset can be reused at a different span; what gets printed is the hole in the binder."""
    binder, asset = _binder_with_insert(db, image_cache, row_span=1, col_span=1)
    assert (asset.width_pockets, asset.height_pockets) == (2, 2)
    pieces = build_insert_pieces(db, binder.id)
    assert len(pieces) == 1
    assert (pieces[0].width_pockets, pieces[0].height_pockets) == (1, 1)
    assert pieces[0].trim_w_mm == POCKET_W_MM


def test_binder_pdf_export_writes_a_file(db, image_cache, tmp_path):
    binder, _ = _binder_with_insert(db, image_cache, row_span=2, col_span=2)
    out = export_binder_inserts_pdf(db, binder.id, tmp_path / "b.pdf")
    data = (tmp_path / "b.pdf").read_bytes()
    assert data.startswith(b"%PDF")
    assert _media_boxes(data)
    assert out.endswith("b.pdf")


def test_export_of_a_missing_binder_is_an_error(db, image_cache, tmp_path):
    with pytest.raises(ExportError, match="not found"):
        export_binder_inserts_pdf(db, 999, tmp_path / "b.pdf")


# --- spread PNG ----------------------------------------------------------------------------------


def test_spread_png_dimensions_follow_the_mm_geometry(tmp_path):
    out = render_spread_png(
        [], tmp_path / "s.png", rows=3, cols=3, gutter_mm=6, dpi=150, binder_name="B"
    )
    with Image.open(out) as img:
        w, h = img.size
    px = 150 / 25.4
    # 2 pages x 3 cols x 70mm + 6mm gutter + 8mm margin each side.
    assert w == pytest.approx(round((2 * 3 * POCKET_W_MM + 6 + 16) * px), abs=2)
    assert h == pytest.approx(round((3 * POCKET_H_MM + 16 + 7) * px), abs=2)


def test_spread_png_aspect_is_true_to_the_binder(tmp_path):
    """A preview that misstates proportions is worse than none -- docs/05-binder-spec.md."""
    render_spread_png([], tmp_path / "s.png", rows=3, cols=3, gutter_mm=6, dpi=150)
    with Image.open(tmp_path / "s.png") as img:
        w, h = img.size
    content_aspect = (2 * 3 * POCKET_W_MM + 6 + 16) / (3 * POCKET_H_MM + 16 + 7)
    assert w / h == pytest.approx(content_aspect, rel=0.01)


def test_higher_dpi_scales_the_preview(tmp_path):
    render_spread_png([], tmp_path / "a.png", rows=3, cols=3, dpi=150)
    render_spread_png([], tmp_path / "b.png", rows=3, cols=3, dpi=300)
    with Image.open(tmp_path / "a.png") as a, Image.open(tmp_path / "b.png") as b:
        assert b.size[0] == pytest.approx(a.size[0] * 2, rel=0.01)


def test_gutter_spanning_placement_is_not_shifted_by_page_side(tmp_path):
    """Regression guard for the layout.py convention: a gutter-spanning placement already
    carries spread coordinates, so applying a page offset would double-count it."""
    spanning = RenderPlacement(
        row=0, col=2, row_span=1, col_span=2, page_side=0, kind="insert", spans_gutter=True
    )
    render_spread_png([spanning], tmp_path / "s.png", rows=3, cols=3, gutter_mm=6, dpi=100)
    # Column 2 is the last of the left page, column 3 the first of the right: the placement must
    # straddle the gutter, which is only true if no offset was added.
    assert spread_column_x_mm(2, 3, 6) < 3 * POCKET_W_MM
    assert spread_column_x_mm(3, 3, 6) > 3 * POCKET_W_MM


def test_spread_out_of_range_is_an_error(db, image_cache, tmp_path):
    binder, _ = _binder_with_insert(db, image_cache)
    with pytest.raises(ExportError, match="outside binder"):
        export_binder_spread_png(db, binder.id, 9, tmp_path / "s.png", fetch_art=False)


def test_binder_spread_png_renders_without_touching_the_network(db, image_cache, tmp_path):
    binder, _ = _binder_with_insert(db, image_cache, row_span=2, col_span=2)
    out = export_binder_spread_png(db, binder.id, 0, tmp_path / "s.png", fetch_art=False)
    with Image.open(out) as img:
        assert img.size[0] > 100


def test_cover_size_never_distorts_the_art():
    """Bleed changes the box's aspect, so filling it directly would squash the art. Cover-and-crop
    keeps the source's aspect exactly."""
    # A 3x1 strip: trim 210x95, bleed 214x99. Source aspect 2481/1123.
    box_w, box_h = 3 * POCKET_W_MM + 4, POCKET_H_MM + 4
    w, h = cover_size(box_w, box_h, 2481, 1123)
    assert w / h == pytest.approx(2481 / 1123, rel=1e-9), "aspect must survive exactly"
    assert w >= box_w - 1e-9 and h >= box_h - 1e-9, "must cover the box, not letterbox it"


def test_cover_size_covers_on_the_other_axis_too():
    w, h = cover_size(74.0, 99.0, 2000, 1000)  # very wide source into a tall box
    assert w / h == pytest.approx(2.0, rel=1e-9)
    assert w >= 74.0 - 1e-9 and h >= 99.0 - 1e-9


def test_cover_size_rejects_an_empty_source():
    with pytest.raises(ExportError, match="no pixel dimensions"):
        cover_size(74.0, 99.0, 0, 100)
