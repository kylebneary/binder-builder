"""Perceptual colour for the Michi layout: sRGB -> CIELAB, CIEDE2000, and dominant-colour
extraction (roadmap 3.6).

Why hand-written rather than a dependency: this is about sixty lines of fiddly arithmetic, and the
alternative is a package pulled in for one function. The insurance is `test_color.py`, which checks
CIEDE2000 against the published reference pairs from Sharma, Wu & Dalal (2005) -- the standard test
data for exactly this, precisely because implementations get the hue-quadrant wraparound wrong.

Why not RGB: docs/05-binder-spec.md is explicit that RGB distance does not match perceived
similarity, and colour-themed pages built on it come out visibly wrong. Everything here works in
CIELAB with D65, which is what `card.dominant_color_lab` stores.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# D65 white point, 2-degree observer. The illuminant the sRGB spec is defined against.
WHITE_D65 = (95.047, 100.000, 108.883)

# The illustration window on a standard Pokemon card, as fractions of (left, top, right, bottom).
# Everything outside it is card frame: a type-coloured border, the yellow card edge, the attack
# text box. See `dominant_lab` for the measurement that produced these numbers.
ART_WINDOW = (0.09, 0.11, 0.91, 0.52)

# sRGB -> CIEXYZ, the matrix from IEC 61966-2-1.
_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)


def srgb_to_linear(channel: np.ndarray) -> np.ndarray:
    """Undo the sRGB transfer function. Vectorised: this runs over every pixel of every card."""
    c = np.asarray(channel, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_to_lab(rgb: tuple[float, float, float] | np.ndarray) -> tuple[float, float, float]:
    """One sRGB colour (0-255) to CIELAB."""
    lab = srgb_array_to_lab(np.asarray([rgb], dtype=float))
    return (float(lab[0, 0]), float(lab[0, 1]), float(lab[0, 2]))


def srgb_array_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(N, 3) sRGB in 0-255 to (N, 3) CIELAB."""
    linear = srgb_to_linear(np.asarray(rgb, dtype=float) / 255.0)
    xyz = linear @ _RGB_TO_XYZ.T * 100.0
    scaled = xyz / np.asarray(WHITE_D65)
    # The CIE piecewise cube root; the linear segment near zero keeps the derivative finite.
    epsilon, kappa = 216 / 24389, 24389 / 27
    f = np.where(scaled > epsilon, np.cbrt(scaled), (kappa * scaled + 16) / 116)
    return np.stack(
        [116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1
    )


def delta_e2000(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
    *,
    k_l: float = 1.0,
    k_c: float = 1.0,
    k_h: float = 1.0,
) -> float:
    """CIEDE2000 colour difference.

    Follows the formulation in Sharma, Wu & Dalal (2005). The parts implementations habitually get
    wrong, and which the reference pairs in the tests exist to catch, are the hue-mean quadrant
    rules below and the fact that a zero chroma must force the hue terms to zero rather than
    letting atan2(0, 0) leak in.
    """
    l1, a1, b1 = (float(v) for v in lab1)
    l2, a2, b2 = (float(v) for v in lab2)

    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2
    # The G term stretches a* in the low-chroma region, where CIELAB is least uniform.
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25.0**7))) if c_bar > 0 else 0.5
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def hue(ap: float, bp: float) -> float:
        if ap == 0 and bp == 0:
            return 0.0
        return math.degrees(math.atan2(bp, ap)) % 360.0

    h1p, h2p = hue(a1p, b1), hue(a2p, b2)

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dhp_big = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)

    l_bar = (l1 + l2) / 2
    c_bar_p = (c1p + c2p) / 2
    if c1p * c2p == 0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        h_bar = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        h_bar = (h1p + h2p + 360) / 2
    else:
        h_bar = (h1p + h2p - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar))
        + 0.32 * math.cos(math.radians(3 * h_bar + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))
    )
    d_theta = 30 * math.exp(-(((h_bar - 275) / 25) ** 2))
    r_c = 2 * math.sqrt(c_bar_p**7 / (c_bar_p**7 + 25.0**7)) if c_bar_p > 0 else 0.0
    s_l = 1 + (0.015 * (l_bar - 50) ** 2) / math.sqrt(20 + (l_bar - 50) ** 2)
    s_c = 1 + 0.045 * c_bar_p
    s_h = 1 + 0.015 * c_bar_p * t
    r_t = -math.sin(math.radians(2 * d_theta)) * r_c

    term_l = dlp / (k_l * s_l)
    term_c = dcp / (k_c * s_c)
    term_h = dhp_big / (k_h * s_h)
    return math.sqrt(term_l**2 + term_c**2 + term_h**2 + r_t * term_c * term_h)


def chroma(lab: tuple[float, float, float]) -> float:
    """Distance from the neutral axis -- how colourful, independent of lightness."""
    return math.hypot(lab[1], lab[2])


def dominant_lab(
    image_path: str | Path,
    *,
    k: int = 5,
    sample_px: int = 96,
    art_box: tuple[float, float, float, float] = ART_WINDOW,
    min_cluster_share: float = 0.08,
    seed: int = 0,
) -> tuple[float, float, float] | None:
    """The card's characteristic colour, as CIELAB.

    k-means over the pixels, then the *most saturated cluster that is still big enough to matter*
    rather than simply the largest. A Pokemon card is mostly yellow-white border and grey text box;
    taking the biggest cluster would report nearly every card as beige and make colour-themed pages
    meaningless. `min_cluster_share` is what stops the opposite failure -- a hundred bright pixels
    of holo glare defining the card.

    Sampling is restricted to `art_box`, the illustration window, not the whole card. This is not
    a nicety: measured against real sv8 art, trimming a uniform 10% border still leaves the type-
    coloured frame and the yellow card edge dominating every cluster, and 60 cards came back as
    the same yellow-green to within a unit of Lab -- including a Metal-type card. Cropping to the
    art window instead produces colours that actually differ per card. Full-art and illustration-
    rare cards carry art across the whole face, so the window still lands on illustration for
    those.

    Returns None when the image cannot be read, so a bad file skips one card instead of failing a
    whole set.
    """
    from PIL import Image

    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            w, h = img.size
            left, top, right, bottom = (
                int(w * art_box[0]), int(h * art_box[1]), int(w * art_box[2]), int(h * art_box[3])
            )
            if right - left > 8 and bottom - top > 8:
                img = img.crop((left, top, right, bottom))
            img.thumbnail((sample_px, sample_px))
            pixels = np.asarray(img, dtype=float).reshape(-1, 3)
    except (OSError, ValueError):
        return None

    if pixels.size == 0:
        return None

    lab = srgb_array_to_lab(pixels)
    centroids = _kmeans(lab, k=k, seed=seed)
    if centroids is None:
        return None
    centres, counts = centroids

    share = counts / counts.sum()
    eligible = np.flatnonzero(share >= min_cluster_share)
    if eligible.size == 0:
        eligible = np.flatnonzero(counts == counts.max())

    chromas = np.hypot(centres[eligible, 1], centres[eligible, 2])
    winner = eligible[int(np.argmax(chromas))]
    return (float(centres[winner, 0]), float(centres[winner, 1]), float(centres[winner, 2]))


def _kmeans(
    points: np.ndarray, *, k: int, seed: int, iterations: int = 25
) -> tuple[np.ndarray, np.ndarray] | None:
    """Plain Lloyd's algorithm with k-means++ seeding, vectorised.

    Seeded so a given image always yields the same colour -- an extraction that drifts between runs
    would make cached values and fresh ones disagree for no reason the user could see.
    """
    if points.shape[0] == 0:
        return None
    k = min(k, points.shape[0])
    rng = np.random.default_rng(seed)

    # k-means++: spread the initial centres out, so a rare accent colour is not always swallowed.
    centres = [points[rng.integers(points.shape[0])]]
    for _ in range(1, k):
        d2 = np.min(
            ((points[:, None, :] - np.asarray(centres)[None, :, :]) ** 2).sum(axis=2), axis=1
        )
        total = d2.sum()
        if total <= 0:
            centres.append(points[rng.integers(points.shape[0])])
            continue
        centres.append(points[rng.choice(points.shape[0], p=d2 / total)])
    centres_arr = np.asarray(centres, dtype=float)

    labels = np.zeros(points.shape[0], dtype=int)
    for _ in range(iterations):
        distances = ((points[:, None, :] - centres_arr[None, :, :]) ** 2).sum(axis=2)
        new_labels = np.argmin(distances, axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for i in range(k):
            member = points[labels == i]
            if member.size:
                centres_arr[i] = member.mean(axis=0)

    counts = np.bincount(labels, minlength=k).astype(float)
    keep = counts > 0
    return centres_arr[keep], counts[keep]
