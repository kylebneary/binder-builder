from app.binder.layout import Rect, validate_page


def test_non_overlapping_rects_are_valid():
    rects = [Rect(0, 0), Rect(0, 1, col_span=2), Rect(1, 0, row_span=2, col_span=3)]
    assert validate_page(rects, rows=3, cols=3) == []


def test_overlap_is_detected():
    rects = [Rect(0, 0, col_span=2), Rect(0, 1)]
    errors = validate_page(rects, rows=3, cols=3)
    assert any("overlap" in e for e in errors)


def test_out_of_bounds_is_detected():
    errors = validate_page([Rect(2, 2, row_span=2)], rows=3, cols=3)
    assert any("does not fit" in e for e in errors)
