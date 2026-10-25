"""CIELAB conversion and CIEDE2000 (roadmap 3.6).

CIEDE2000 is checked against the published reference pairs from Sharma, Wu & Dalal (2005), which
exist precisely because implementations get this wrong in ways that look plausible. The pairs
below are the ones that exercise the parts that actually break: the hue-mean quadrant rules
(pairs across the 0/360 boundary), the zero-chroma guard, and the RT rotation term in the blue
region.

If one of these ever fails, the arithmetic is wrong -- do not adjust the expectation.
"""
import math

import numpy as np
import pytest
from app.binder.color import (
    chroma,
    delta_e2000,
    dominant_lab,
    srgb_array_to_lab,
    srgb_to_lab,
)
from PIL import Image

# (lab1, lab2, expected dE00) from the Sharma/Wu/Dalal supplementary test data.
REFERENCE_PAIRS = [
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
]


@pytest.mark.parametrize(("lab1", "lab2", "expected"), REFERENCE_PAIRS)
def test_delta_e2000_matches_the_published_reference(lab1, lab2, expected):
    assert delta_e2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)


def test_delta_e2000_is_symmetric():
    for lab1, lab2, _ in REFERENCE_PAIRS:
        assert delta_e2000(lab1, lab2) == pytest.approx(delta_e2000(lab2, lab1), abs=1e-12)


def test_identical_colours_have_zero_difference():
    assert delta_e2000((50.0, 2.5, -3.0), (50.0, 2.5, -3.0)) == pytest.approx(0.0, abs=1e-12)


def test_two_neutrals_do_not_trip_the_zero_chroma_guard():
    """atan2(0, 0) is 0, which would fabricate a hue for a grey. The difference between two greys
    must come from lightness alone."""
    d = delta_e2000((40.0, 0.0, 0.0), (60.0, 0.0, 0.0))
    assert d > 0
    # Pure lightness difference: 20 / SL, with L-bar 50 making SL exactly 1.
    assert d == pytest.approx(20.0, abs=1e-9)


# --- sRGB -> CIELAB -------------------------------------------------------------------------------


def test_white_black_and_red_convert_to_their_canonical_lab_values():
    assert srgb_to_lab((255, 255, 255)) == pytest.approx((100.0, 0.0, 0.0), abs=1e-3)
    assert srgb_to_lab((0, 0, 0)) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    # The textbook sRGB red.
    assert srgb_to_lab((255, 0, 0)) == pytest.approx((53.241, 80.092, 67.203), abs=1e-2)


def test_greys_have_no_chroma():
    # Not exactly zero: D65 as tabulated is not precisely sRGB's white, leaving ~4e-6 of residue.
    # That is nothing on a 0-130 chroma scale, but it is not 1e-6 either.
    for v in (32, 128, 200):
        lab = srgb_to_lab((v, v, v))
        assert chroma(lab) == pytest.approx(0.0, abs=1e-4)


def test_lightness_increases_with_grey_level():
    lightnesses = [srgb_to_lab((v, v, v))[0] for v in (0, 64, 128, 192, 255)]
    assert lightnesses == sorted(lightnesses)


def test_array_conversion_matches_the_scalar_one():
    rgb = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255], [10, 20, 30]], dtype=float)
    batch = srgb_array_to_lab(rgb)
    for row, expected in zip(batch, [srgb_to_lab(tuple(v)) for v in rgb], strict=True):
        assert tuple(row) == pytest.approx(expected, abs=1e-9)


# --- dominant colour ------------------------------------------------------------------------------


def _card_like(tmp_path, name, border, art):
    """A crude stand-in for a card: a wide pale border around a block of art."""
    img = Image.new("RGB", (200, 280), border)
    for x in range(40, 160):
        for y in range(56, 224):
            img.putpixel((x, y), art)
    path = tmp_path / name
    img.save(path)
    return path


def test_dominant_colour_finds_the_art_not_the_border(tmp_path):
    """A Pokemon card is mostly pale border and grey text box. Taking the largest cluster would
    report almost every card as beige, which is why the most *saturated* large cluster wins."""
    path = _card_like(tmp_path, "red.png", border=(245, 240, 220), art=(200, 30, 30))
    lab = dominant_lab(path)
    assert lab is not None
    assert chroma(lab) > 40, "picked a near-neutral cluster over the saturated art"
    # Close to sRGB red-ish, and much nearer to it than to the border colour.
    assert delta_e2000(lab, srgb_to_lab((200, 30, 30))) < delta_e2000(
        lab, srgb_to_lab((245, 240, 220))
    )


def test_dominant_colour_distinguishes_two_differently_coloured_cards(tmp_path):
    red = dominant_lab(_card_like(tmp_path, "r.png", (245, 240, 220), (200, 30, 30)))
    blue = dominant_lab(_card_like(tmp_path, "b.png", (245, 240, 220), (30, 60, 200)))
    assert red is not None and blue is not None
    assert delta_e2000(red, blue) > 30, "a red and a blue card must not read as the same colour"


def test_dominant_colour_is_deterministic(tmp_path):
    """k-means is seeded: the same art must give the same colour every run, or cached values and
    freshly computed ones would disagree for no visible reason."""
    path = _card_like(tmp_path, "c.png", (245, 240, 220), (30, 160, 90))
    assert dominant_lab(path) == dominant_lab(path)


def test_a_grey_card_still_returns_a_colour(tmp_path):
    """No cluster clears the saturation bar, so the largest one is used rather than returning
    nothing."""
    path = _card_like(tmp_path, "g.png", (200, 200, 200), (120, 120, 120))
    lab = dominant_lab(path)
    assert lab is not None
    assert chroma(lab) < 5


def test_an_unreadable_file_returns_none_rather_than_raising(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    assert dominant_lab(bad) is None


def test_hue_angle_wraps_correctly():
    """Sanity check on the convention the layout uses to order cards around the wheel."""
    red = srgb_to_lab((255, 0, 0))
    angle = math.degrees(math.atan2(red[2], red[1])) % 360.0
    assert 30 < angle < 50, f"sRGB red should sit near 40 degrees, got {angle}"
