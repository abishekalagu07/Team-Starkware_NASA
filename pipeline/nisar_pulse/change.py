"""Change detection recipes, each tied to a scattering mechanism.

| change            | channel        | mechanism                                   | signature            |
|-------------------|----------------|---------------------------------------------|----------------------|
| open-water flood  | HH (or VV)     | specular reflection away from sensor        | strong DROP, < ~-18 dB|
| flooded vegetation| HH, L-band     | water-trunk double bounce                   | HH RISE (+3..+10 dB) |
| burn / clearing   | HV             | loss of canopy volume scattering            | HV DROP (-3..-6 dB)  |
| crop growth       | HV, HV/HH, RVI | growing canopy volume                       | seasonal HV rise     |
| paddy rice        | HH/HV time series | flooded field (dark) -> rapid canopy growth | V-shaped curve     |
"""
from __future__ import annotations

from datetime import date

import numpy as np

from .sar import from_db, to_db

# class codes are shared with the web legend (see LEGENDS)
FLOOD_CLASSES = {0: "No change", 1: "Permanent water", 2: "New open water (flood)",
                 3: "Receded water", 4: "Flooded vegetation (double bounce)"}
DISTURB_CLASSES = {0: "No change", 1: "Vegetation loss (burn / clearing)", 2: "Vegetation gain / regrowth"}
CROP_CLASSES = {0: "Stable / non-crop", 1: "Paddy rice (flooded, then rapid growth)",
                2: "Other active cropland (incl. unflooded rice)"}


def log_ratio_db(pre_db, post_db):
    """Difference of dB images == 10*log10(post/pre). Robust to multiplicative speckle."""
    return (np.asarray(post_db, "f4") - np.asarray(pre_db, "f4")).astype("f4")


def otsu_threshold(values, bins: int = 256, clip=None) -> float:
    v = np.asarray(values, "f8")
    v = v[np.isfinite(v)]
    if clip is not None:
        v = v[(v >= clip[0]) & (v <= clip[1])]
    if v.size < 10:
        return float("nan")
    hist, edges = np.histogram(v, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers) / np.maximum(w0, 1)
    m1 = (np.sum(hist * centers) - np.cumsum(hist * centers)) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(centers[np.argmax(between[:-1])])


def water_threshold(hh_db, default=-18.0, bounds=(-24.0, -13.0)) -> float:
    """Otsu on the HH histogram, constrained to physically plausible water levels.

    Falls back to ``default`` when the scene is not bimodal (little water present).
    """
    t = otsu_threshold(hh_db, clip=(-35, 5))
    if not np.isfinite(t) or not (bounds[0] <= t <= bounds[1]):
        return default
    return t


def qc_dates(hh_stack_db, water_db=None, scene_tol_db=4.0, water_tol_db=6.0, min_water_px=200):
    """Flag acquisitions that are radiometrically inconsistent with the rest of the stack.

    (a) the scene-wide median HH is more than ``scene_tol_db`` BRIGHTER than the stack median;
    (b) persistently dark pixels (water in the temporal median) brighten by more than
        ``water_tol_db`` - wind-roughened water, a calibration slip or a corrupt product.
    Only brightening is suspicious: a whole scene darkens for real when a floodplain or a
    rice belt goes under water (Punjab in July drops 6-8 dB), and those are the dates that
    carry the signal. A fixed water threshold cannot classify a brightened date, so it is
    left out. Never flags more than a third of the stack. Returns (bad_mask, reasons).
    """
    import warnings

    T = hh_stack_db.shape[0]
    bad = np.zeros(T, bool)
    reasons = [""] * T
    if T < 4:
        return bad, reasons
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        scene = np.array([np.nanmedian(f) for f in hh_stack_db])
        med = np.nanmedian(hh_stack_db, 0)
    dev = scene - np.nanmedian(scene)
    for i in np.where(dev > scene_tol_db)[0]:
        bad[i] = True
        reasons[i] = f"scene median {dev[i]:+.1f} dB brighter than stack"
    thr = water_db if water_db is not None else water_threshold(med)
    pw = med < thr
    if pw.sum() >= min_water_px:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            wm = np.array([np.nanmedian(f[pw]) for f in hh_stack_db])
        wdev = wm - np.nanmedian(wm)
        for i in np.where(wdev > water_tol_db)[0]:
            bad[i] = True
            reasons[i] = (reasons[i] + "; " if reasons[i] else "") + f"persistent water {wdev[i]:+.1f} dB brighter"
    if bad.sum() > T // 3:   # the stack itself is inconsistent: keep everything, say nothing
        return np.zeros(T, bool), [""] * T
    return bad, reasons


def flood_classes(pre_hh_db, post_hh_db, pre_hv_db=None, post_hv_db=None,
                  water_db=None, dbounce_db=3.0):
    """Pre/post flood map with the L-band flooded-vegetation class.

    Flooded vegetation is the reason to use NISAR L-band rather than C-band: the
    24 cm wave reaches the water under the canopy and bounces back off trunks,
    so HH *brightens*. HV changes much less (double bounce is a co-pol mechanism),
    which separates it from simple vegetation growth (HV would rise too).
    """
    thr = water_db if water_db is not None else water_threshold(np.concatenate([
        np.ravel(pre_hh_db), np.ravel(post_hh_db)]))
    pre_w = pre_hh_db < thr
    post_w = post_hh_db < thr
    d_hh = log_ratio_db(pre_hh_db, post_hh_db)
    cls = np.zeros(pre_hh_db.shape, np.uint8)
    cls[pre_w & post_w] = 1
    cls[~pre_w & post_w] = 2
    cls[pre_w & ~post_w] = 3
    fv = (~pre_w) & (~post_w) & (d_hh > dbounce_db)
    if pre_hv_db is not None and post_hv_db is not None:
        d_hv = log_ratio_db(pre_hv_db, post_hv_db)
        fv &= (d_hh - d_hv) > 1.5
    cls[fv] = 4
    cls[~(np.isfinite(pre_hh_db) & np.isfinite(post_hh_db))] = 255
    return cls, float(thr)


def disturbance_classes(hv_stack_db, n_pre: int, drop_db=-3.0, gain_db=3.0,
                        min_pre_hv_db=-20.0, persist: int = 2):
    """Forest loss / burn scars from cross-pol (HV) — volume scattering disappears with the canopy.

    hv_stack_db : (T, ny, nx); first ``n_pre`` frames are the baseline.
    A pixel is 'loss' only if HV stays below baseline+drop for ``persist``
    consecutive post-event frames — kills single-date rain / wind false alarms.
    """
    pre = hv_stack_db[:n_pre]
    post = hv_stack_db[n_pre:]
    base = to_db(np.nanmedian(from_db(pre), axis=0))
    delta = post - base[None]
    loss_hit = delta < drop_db
    gain_hit = delta > gain_db
    loss = _runs(loss_hit, persist) & (base > min_pre_hv_db)
    gain = _runs(gain_hit, persist)
    cls = np.zeros(base.shape, np.uint8)
    cls[gain] = 2
    cls[loss] = 1
    cls[~np.isfinite(base)] = 255
    d_final = to_db(np.nanmedian(from_db(post), axis=0)) - base
    return cls, d_final


def _runs(hits, k):
    """True where a pixel has >= k consecutive True along axis 0."""
    if k <= 1:
        return hits.any(axis=0)
    run = np.zeros(hits.shape[1:], np.int16)
    best = np.zeros_like(run)
    for h in hits:
        run = np.where(h, run + 1, 0)
        best = np.maximum(best, run)
    return best >= k


def zscore_stack(stack_db, n_base: int):
    """Temporal z-score of each frame against the first n_base frames — anomaly time-lapse."""
    base = stack_db[:n_base]
    mu = np.nanmean(base, 0)
    sd = np.nanstd(base, 0)
    sd = np.where(sd < 0.5, 0.5, sd)  # speckle floor
    return ((stack_db - mu) / sd).astype("f4")


def crop_phenology(hv_stack_db, dates: list[date], hh_stack_db=None,
                   flood_db=None, rise_db=5.0, window_days=75, active_range_db=4.0):
    """Per-pixel crop calendar from the radar time series.

    Paddy rice: fields are flooded at transplanting (HH/HV collapse below water
    level), then HV rises fast as the canopy develops — a V-shaped curve that
    optical satellites usually miss under monsoon cloud.
    ``flood_db`` None = the scene's own Otsu water level (same definition the flood
    recipes use), so "flooded" means the same thing everywhere in the app.
    Returns (classes, metrics dict of 2-D arrays).
    """
    t = np.array([(d - dates[0]).days for d in dates])
    lin = from_db(hv_stack_db)
    if flood_db is None:
        flood_db = water_threshold(hh_stack_db if hh_stack_db is not None else hv_stack_db)
    with np.errstate(invalid="ignore"):
        rng = np.nanmax(hv_stack_db, 0) - np.nanmin(hv_stack_db, 0)
    filled = np.where(np.isfinite(hv_stack_db), hv_stack_db, np.inf)
    i_min = np.argmin(filled, 0)
    filled_max = np.where(np.isfinite(hv_stack_db), hv_stack_db, -np.inf)
    i_max = np.argmax(filled_max, 0)
    v_min = np.take_along_axis(hv_stack_db, i_min[None], 0)[0]
    flood_src = hh_stack_db if hh_stack_db is not None else hv_stack_db
    flood_min = np.take_along_axis(flood_src, i_min[None], 0)[0]
    # max HV within window after the minimum
    T = hv_stack_db.shape[0]
    after_max = np.full(v_min.shape, -np.inf, "f4")
    for k in range(T):
        dt = t[k] - t[i_min]
        ok = (dt > 0) & (dt <= window_days)
        after_max = np.where(ok & np.isfinite(hv_stack_db[k]), np.maximum(after_max, hv_stack_db[k]), after_max)
    rice = (flood_min < flood_db) & ((after_max - v_min) > rise_db)
    active = rng > active_range_db
    cls = np.zeros(v_min.shape, np.uint8)
    cls[active] = 2
    cls[rice] = 1
    cls[~np.isfinite(np.nanmean(lin, 0))] = 255
    metrics = {"dynamic_range_db": rng.astype("f4"),
               "day_of_min": t[i_min].astype("f4"),
               "day_of_peak": t[i_max].astype("f4")}
    return cls, metrics


def class_areas(cls, pixel_km2: float, names: dict) -> list[dict]:
    valid = cls != 255
    tot = valid.sum() * pixel_km2
    out = []
    for k, name in names.items():
        if k == 0:
            continue
        a = float((cls == k).sum() * pixel_km2)
        out.append({"code": k, "label": name, "area_km2": round(a, 2),
                    "pct": round(100 * a / tot, 2) if tot else 0.0})
    return out


def class_timeseries(stack_db, cls, names: dict, min_px: int = 20) -> list[dict]:
    """Mean backscatter per class per date (linear mean -> dB)."""
    out = []
    for k, name in names.items():
        m = cls == k
        if m.sum() < min_px:
            continue
        vals = [float(np.round(to_db(np.nanmean(from_db(f[m]))), 2)) if np.isfinite(f[m]).any() else None
                for f in stack_db]
        out.append({"code": k, "name": name, "values": vals})
    return out
