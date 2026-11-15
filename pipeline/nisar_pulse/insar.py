"""Interferometry: GUNW phase -> centimetre-scale ground motion.

Sign convention
---------------
d_LOS = SIGN * wavelength / (4*pi) * (phase - ionosphere)

With SIGN = -1 (ISCE-family convention) positive values mean motion *towards* the
satellite (e.g. uplift).
Conventions differ between processors, so **validate once** against a known
signal (USGS finite-fault model, GNSS station, or the polarity of a subsidence bowl)
and flip ``sign`` in sites.yaml if needed. This is the #1 InSAR mistake in hackathons.
"""
from __future__ import annotations

import numpy as np


def los_displacement(phase, wavelength: float, iono=None, sign: float = -1.0):
    """Phase (rad) -> LOS displacement (m). Ionospheric screen is subtracted when given:
    at L-band the ionosphere can add several cm of fake motion, especially near the
    equator and poles — NISAR GUNW ships the screen but does not apply it."""
    ph = np.asarray(phase, "f4")
    if iono is not None:
        ph = ph - np.nan_to_num(np.asarray(iono, "f4"))
    return (sign * wavelength / (4 * np.pi) * ph).astype("f4")


def quality_mask(coherence=None, components=None, min_coh: float = 0.3):
    """Valid where coherence is high and the pixel belongs to a reliably unwrapped component (!=0)."""
    m = None
    if coherence is not None:
        m = np.asarray(coherence) >= min_coh
    if components is not None:
        c = np.asarray(components)
        cm = np.isfinite(c) & (c != 0)
        m = cm if m is None else (m & cm)
    return m


def reference(disp, ref_mask=None, largest_component=None, components=None):
    """Remove the arbitrary phase constant: subtract the median over a stable reference
    area (far field / bedrock). With multiple connected components each may carry a
    different 2*pi ambiguity — keep only the largest component for a quick, honest map."""
    d = np.array(disp, "f4")
    if components is not None and largest_component is None:
        c = np.asarray(components)
        vals, counts = np.unique(c[np.isfinite(c) & (c != 0)], return_counts=True)
        if vals.size:
            largest_component = vals[np.argmax(counts)]
    if components is not None and largest_component is not None:
        d[np.asarray(components) != largest_component] = np.nan
    sel = d if ref_mask is None else np.where(ref_mask, d, np.nan)
    return d - np.nanmedian(sel)


def far_field_mask(shape, center_rc, frac: float = 0.15):
    """Pixels farther from the epicentre than (1-frac) of the max distance: a reference ring."""
    yy, xx = np.indices(shape)
    r = np.hypot(yy - center_rc[0], xx - center_rc[1])
    return r >= np.nanmax(r) * (1 - frac)


def rewrap(disp_m, wavelength: float):
    """Re-wrap displacement into fringes: one colour cycle = wavelength/2 of LOS motion
    (11.9 cm at L-band). The classic 'earthquake rainbow' that scientists recognise."""
    half = wavelength / 2
    return (np.mod(disp_m, half) / half).astype("f4")


def chain_pairs(disps: list[np.ndarray]):
    """Cumulative displacement from consecutive 12-day pairs (simple small-baseline chain).
    Gaps propagate as NaN — for production use MintPy SBAS on GSLC/GUNW stacks."""
    out, acc = [], None
    for d in disps:
        acc = d.copy() if acc is None else acc + d
        out.append(acc.copy())
    return out


def los_unit_vector(incidence_deg, heading_deg, look="right"):
    """ENU components of the ground->satellite unit vector.

    heading: satellite flight direction, degrees clockwise from north.
    Read the product's identification/lookDirection and pass it as ``look``.
    """
    inc = np.radians(incidence_deg)
    head = np.radians(heading_deg)
    look_az = head + (np.pi / 2 if look == "right" else -np.pi / 2)  # direction sat looks
    # ground->satellite points opposite the look azimuth on the horizontal plane
    e = -np.sin(inc) * np.sin(look_az)
    n = -np.sin(inc) * np.cos(look_az)
    u = np.cos(inc)
    return e, n, u


def decompose_asc_desc(los_a, los_d, inc_a, head_a, inc_d, head_d, look="left"):
    """Solve East & Up from ascending + descending LOS (north is poorly resolved by
    polar-orbiting SAR and is neglected). Turns two 1-D measurements into a map of
    uplift/subsidence and horizontal motion — great for strike-slip quakes."""
    ea, _, ua = los_unit_vector(inc_a, head_a, look)
    ed, _, ud = los_unit_vector(inc_d, head_d, look)
    det = ea * ud - ed * ua
    east = (los_a * ud - los_d * ua) / det
    up = (ea * los_d - ed * los_a) / det
    return east.astype("f4"), up.astype("f4")


def offsets_to_velocity(along_m, range_m, days: float, incidence_deg: float | None = None):
    """GOFF pixel offsets (m) -> surface speed (m/day). Slant-range offsets are projected
    to ground range with 1/sin(incidence) when the angle is known."""
    rg = np.asarray(range_m, "f4")
    if incidence_deg is not None:
        rg = rg / np.sin(np.radians(incidence_deg))
    return (np.hypot(np.asarray(along_m, "f4"), rg) / days).astype("f4")
