"""Radiometric helpers. Rule #1 of SAR arithmetic: average in LINEAR power, display in dB."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter


def to_db(lin, floor=1e-6):
    lin = np.asarray(lin, dtype="f4")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = 10 * np.log10(np.where(lin > 0, np.maximum(lin, floor), np.nan))
    return out.astype("f4")


def from_db(db):
    return (10 ** (np.asarray(db, dtype="f4") / 10)).astype("f4")


def nanmean_db(stack_db, axis=0):
    """Correct way to average dB images: convert to linear, average, convert back."""
    import warnings

    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        return to_db(np.nanmean(from_db(stack_db), axis=axis))


def multilook(lin, ly: int, lx: int):
    """Block-average (linear power) — trades resolution for fewer speckle-induced false alarms."""
    ny, nx = lin.shape[0] // ly * ly, lin.shape[1] // lx * lx
    a = lin[:ny, :nx].reshape(ny // ly, ly, nx // lx, lx)
    with np.errstate(invalid="ignore"):
        return np.nanmean(a, axis=(1, 3)).astype("f4")


def _nan_uniform(a, size):
    valid = np.isfinite(a).astype("f4")
    filled = np.where(valid > 0, a, 0).astype("f4")
    num = uniform_filter(filled, size)
    den = uniform_filter(valid, size)
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / den, den


def lee_filter(lin, size: int = 5, looks: float = 4.0):
    """Classic Lee (1980) adaptive speckle filter, NaN-aware.

    Smooths homogeneous areas (fields, water) while preserving edges (field
    boundaries, shorelines) — which is exactly what change detection needs.
    ``looks`` = equivalent number of looks of the input (GCOV numberOfLooks).
    """
    lin = np.asarray(lin, dtype="f4")
    # A NaN looks value (e.g. numberOfLooks sampled in a no-data area) would turn every
    # output pixel NaN, since max(nan, 1.0) is nan. Fall back to a typical GCOV value.
    if looks is None or not np.isfinite(looks) or looks <= 0:
        looks = 4.0
    m, cover = _nan_uniform(lin, size)
    m2, _ = _nan_uniform(lin * lin, size)
    var = np.maximum(m2 - m * m, 0)
    cu2 = 1.0 / max(looks, 1.0)
    var_x = np.maximum((var - m * m * cu2) / (1 + cu2), 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(var > 0, var_x / var, 0)
    out = m + k * (np.where(np.isfinite(lin), lin, m) - m)
    out[cover == 0] = np.nan
    return out.astype("f4")


def cross_pol_ratio_db(hh_lin, hv_lin):
    """HV/HH in dB: high for volume scatterers (forest, mature crops), very low for water/bare soil."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return to_db(hv_lin / hh_lin)


def rvi_dual(co_lin, cross_lin):
    """Dual-pol Radar Vegetation Index 4*X/(C+X) (Trudel et al. 2012). ~0 bare soil, ->1 dense canopy."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return (4 * cross_lin / (co_lin + cross_lin)).astype("f4")


def rgb_composite(hh_lin, hv_lin, ranges=((-25.0, 0.0), (-30.0, -8.0), (0.0, 15.0))):
    """Standard dual-pol false colour: R=HH (surface/double bounce), G=HV (volume), B=HH/HV.

    Forest -> green, water -> black, urban & flooded forest -> bright/magenta, bare soil -> blue.
    FIXED dB stretches (not per-image percentiles) so colours are comparable through a
    time-lapse — a per-frame stretch would invent change that is not there.
    Returns uint8 (ny, nx, 4) with alpha=0 where invalid.
    """
    hh, hv = to_db(hh_lin), to_db(hv_lin)
    chans = []
    for c, (lo, hi) in zip((hh, hv, hh - hv), ranges):
        chans.append(np.clip((c - lo) / (hi - lo), 0, 1))
    rgb = np.stack(chans, -1)
    alpha = np.isfinite(hh) & np.isfinite(hv)
    out = np.zeros(hh.shape + (4,), np.uint8)
    out[..., :3] = np.nan_to_num(rgb * 255).astype(np.uint8)
    out[..., 3] = alpha * 255
    return out
