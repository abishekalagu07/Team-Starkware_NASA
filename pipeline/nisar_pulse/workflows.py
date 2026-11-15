"""End-to-end recipes: (records of one stack) -> web layers + stats + charts.

Each ``process_*`` function takes already-read records, so the very same code runs on
real NISAR products (``fetch_*`` -> ASF) and on the synthetic demo (scripts/make_demo_data.py).

record (GCOV) = {"date": datetime, "data": {"HHHH": lin, "HVHV": lin}, "x", "y", "epsg", "looks"}
record (GUNW) = {"ref": datetime, "sec": datetime, "data": {...}, "x", "y", "epsg", "wavelength"}
record (GOFF) = {"ref", "sec", "data": {"alongTrackOffset","slantRangeOffset"}, "x", "y", "epsg"}
"""
from __future__ import annotations

import os
import warnings
from datetime import datetime

import numpy as np

from . import change as ch
from . import export as ex
from . import geo, insar, sar

warnings.filterwarnings("ignore", message="Mean of empty slice")
warnings.filterwarnings("ignore", message="All-NaN slice")

NEUTRAL = "#8a8985"
LEGEND_RGB = {"type": "rgb", "items": [
    {"label": "HH: surface & double bounce", "color": "#e34948"},
    {"label": "HV: volume (vegetation)", "color": "#1baf7a"},
    {"label": "HH/HV ratio", "color": "#2a78d6"}]}


def _date(s):
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(str(s).replace("Z", ""))


def _class_legend(names, colors):
    return {"type": "classes", "items": [{"code": k, "label": names[k], "color": colors[k]}
                                         for k in colors]}


def _subsample(items, n):
    if len(items) <= n:
        return items
    idx = np.unique(np.linspace(0, len(items) - 1, n).round().astype(int))
    return [items[i] for i in idx]


def _to_web(rec, layer, site, max_px, method="nearest"):
    arr = rec["data"][layer]
    out, bounds = geo.regrid_to_webmercator(arr, rec["x"], rec["y"], rec["epsg"],
                                            bbox=tuple(site["bbox"]), max_px=max_px, method=method)
    return out, bounds


def _px_km2(site, shape):
    w, s, e, n = site["bbox"]
    lat = np.radians((s + n) / 2)
    return ((e - w) * 111.32 * np.cos(lat) / shape[1]) * ((n - s) * 110.54 / shape[0])


def _base_entry(site, bounds, demo):
    keys = ("id", "name", "region", "continent", "change_type", "product", "bbox", "story",
            "event_date", "epicenters", "s_band", "window")
    e = {k: site[k] for k in keys if k in site}
    w, s, ea, n = bounds
    e.update({"bounds": [w, s, ea, n], "center": [(w + ea) / 2, (s + n) / 2], "demo": bool(demo),
              "band": "L", "layers": {}, "stats": [], "charts": []})
    return e


# =============================================================== GCOV (backscatter)
def process_gcov(site, records, out_dir, max_px=900, demo=False):
    """Flood / wetland / disturbance / crop from a time-ordered GCOV stack."""
    sid = site["id"]
    records = sorted(records, key=lambda r: r["date"])
    # HH and HV series must line up date for date: if the stack is dual-pol, drop the odd
    # acquisition that lacks HV instead of letting the two lists drift out of step.
    if any("HVHV" in r["data"] for r in records):
        dropped = [r["date"] for r in records if "HVHV" not in r["data"]]
        records = [r for r in records if "HVHV" in r["data"]]
        if dropped:
            print(f"[{sid}] dropped {len(dropped)} date(s) without HV: {[f'{d:%Y-%m-%d}' for d in dropped]}")
    dates = [r["date"] for r in records]
    hh, hv = [], []
    bounds = None
    for r in records:
        looks = r.get("looks") or 4.0
        filt = {k: sar.lee_filter(v, 5, looks) for k, v in r["data"].items()}
        rr = dict(r, data=filt)
        a, bounds = _to_web(rr, "HHHH", site, max_px)
        hh.append(sar.to_db(a))
        if "HVHV" in filt:
            b, _ = _to_web(rr, "HVHV", site, max_px)
            hv.append(sar.to_db(b))
    hh = np.stack(hh)
    hv = np.stack(hv) if hv else None
    # radiometric QC: a date whose water or scene level jumps cannot be thresholded like the rest
    bad, why = ch.qc_dates(hh)
    excluded = [{"date": f"{d:%Y-%m-%d}", "reason": w} for d, b, w in zip(dates, bad, why) if b]
    if excluded:
        print(f"[{sid}] excluded {len(excluded)} date(s) by radiometric QC: {excluded}")
        keep = ~bad
        hh, dates = hh[keep], [d for d, k in zip(dates, keep) if k]
        hv = hv[keep] if hv is not None else None
        records = [r for r, k in zip(records, keep) if k]
    T, ny, nx = hh.shape
    pk = _px_km2(site, (ny, nx))
    entry = _base_entry(site, bounds, demo)
    entry["stack"] = dict(records[0].get("stack", {}), n=len(records))   # after any drops
    entry["sources"] = [r["source"] for r in records if r.get("source")]
    entry["excluded_dates"] = excluded
    base = f"sites/{sid}"

    # --- time-lapse frames: dual-pol false colour
    frames = []
    for i, d in enumerate(dates):
        if hv is not None:
            rgba = sar.rgb_composite(sar.from_db(hh[i]), sar.from_db(hv[i]))
            kind, legend = "rgb", LEGEND_RGB
        else:
            rgba = ex.colorize_gray(hh[i])
            kind, legend = "gray", {"type": "gray", "vmin": -25, "vmax": 0, "unit": "dB"}
        url = f"{base}/frames/{d:%Y%m%d}.webp"
        ex.save_png(rgba, os.path.join(out_dir, url))
        frames.append({"date": f"{d:%Y-%m-%d}", "url": url})
    entry["layers"]["frames"] = {"kind": kind, "legend": legend, "items": frames}

    ev = _date(site["event_date"]) if site.get("event_date") else None
    n_pre = max(1, sum(d < ev for d in dates)) if ev else max(1, min(2, T - 1))
    n_pre = min(n_pre, T - 1)
    ct = site["change_type"]
    overlays, charts, stats = [], [], []

    if ct in ("flood", "wetland"):
        pre_hh = sar.nanmean_db(hh[:n_pre])
        pre_hv = sar.nanmean_db(hv[:n_pre]) if hv is not None else None
        thr = ch.water_threshold(hh)
        water_km2, fveg_km2 = [], []
        cls_all = []
        for i in range(T):
            c, _ = ch.flood_classes(pre_hh, hh[i], pre_hv, hv[i] if hv is not None else None, water_db=thr)
            cls_all.append(c)
            water_km2.append(round(float((c == 2).sum() * pk), 1))
            fveg_km2.append(round(float((c == 4).sum() * pk), 1))
        peak = int(np.argmax(np.array(water_km2) + np.array(fveg_km2)))
        cls = cls_all[peak]
        # per-date class maps -> flood time-lapse overlay
        cl_items = []
        for i, d in enumerate(dates):
            url = f"{base}/change/{d:%Y%m%d}.png"
            ex.save_png(ex.colorize_classes(cls_all[i], ex.FLOOD_COLORS), os.path.join(out_dir, url))
            cl_items.append({"date": f"{d:%Y-%m-%d}", "url": url})
        overlays.append({"id": "change", "name": "Flood map (vs. pre-event baseline)", "default": True,
                         "timeseries": True, "items": cl_items,
                         "legend": _class_legend(ch.FLOOD_CLASSES, ex.FLOOD_COLORS)})
        lr = ch.log_ratio_db(pre_hh, hh[peak])
        url = f"{base}/ratio_peak.webp"
        ex.save_png(ex.colorize_diverging(lr, 8), os.path.join(out_dir, url))
        overlays.append({"id": "ratio", "name": f"HH change at peak ({dates[peak]:%d %b})", "url": url,
                         "legend": {"type": "diverging", "vmin": -8, "vmax": 8, "unit": "dB",
                                    "neg": ex.ORANGE, "pos": ex.BLUE, "mid": ex.MID_GRAY,
                                    "neg_label": "darker (open water)", "pos_label": "brighter (double bounce)"}})
        charts.append({"id": "area", "title": "Inundated area", "unit": "km²", "kind": "line",
                       "dates": [f"{d:%Y-%m-%d}" for d in dates],
                       "series": [{"name": "New open water", "values": water_km2, "color": ex.BLUE},
                                  {"name": "Flooded vegetation", "values": fveg_km2, "color": ex.AQUA}]})
        # every "peak" number is read at the same date: the date of maximum total inundation
        stats += [{"label": "Peak inundation (open water + flooded vegetation)",
                   "value": round(water_km2[peak] + fveg_km2[peak], 1), "unit": "km²",
                   "note": f"{dates[peak]:%d %b %Y}"},
                  {"label": "Open water at peak", "value": water_km2[peak], "unit": "km²",
                   "note": f"largest on any date: {max(water_km2)} km² ({dates[int(np.argmax(water_km2))]:%d %b})"},
                  {"label": "Flooded vegetation at peak", "value": fveg_km2[peak], "unit": "km²",
                   "note": "L-band double bounce"},
                  {"label": "Water threshold (Otsu)", "value": round(thr, 1), "unit": "dB HH", "note": "auto"}]
        cube_src, cube_var = hh, "HH"
        ts_cls, names, class_colors = cls, ch.FLOOD_CLASSES, ex.FLOOD_COLORS

    elif ct == "disturbance":
        src = hv if hv is not None else hh
        cls, dfinal = ch.disturbance_classes(src, n_pre, persist=2 if T - n_pre >= 2 else 1)
        url = f"{base}/change.png"
        ex.save_png(ex.colorize_classes(cls, ex.DISTURB_COLORS), os.path.join(out_dir, url))
        overlays.append({"id": "change", "name": "Vegetation loss / gain (HV)", "default": True, "url": url,
                         "legend": _class_legend(ch.DISTURB_CLASSES, ex.DISTURB_COLORS)})
        url = f"{base}/ratio.webp"
        ex.save_png(ex.colorize_diverging(dfinal, 6), os.path.join(out_dir, url))
        overlays.append({"id": "ratio", "name": "HV change after vs. before", "url": url,
                         "legend": {"type": "diverging", "vmin": -6, "vmax": 6, "unit": "dB",
                                    "neg": ex.ORANGE, "pos": ex.BLUE, "mid": ex.MID_GRAY,
                                    "neg_label": "canopy loss", "pos_label": "gain"}})
        areas = ch.class_areas(cls, pk, ch.DISTURB_CLASSES)
        stats += [{"label": a["label"], "value": a["area_km2"], "unit": "km²", "note": f"{a['pct']}% of imaged area"}
                  for a in areas]
        loss = cls == 1
        stats.append({"label": "Mean HV drop in loss area",
                      "value": round(float(np.nanmean(dfinal[loss])), 1) if loss.any() else 0, "unit": "dB",
                      "note": "volume scattering removed"})
        cube_src, cube_var = src, "HV" if hv is not None else "HH"
        ts_cls, names, class_colors = cls, ch.DISTURB_CLASSES, ex.DISTURB_COLORS

    elif ct == "crop":
        src = hv if hv is not None else hh
        cls, met = ch.crop_phenology(src, dates, hh)
        url = f"{base}/change.png"
        ex.save_png(ex.colorize_classes(cls, ex.CROP_COLORS), os.path.join(out_dir, url))
        overlays.append({"id": "change", "name": "Crop type from radar phenology", "default": True, "url": url,
                         "legend": _class_legend(ch.CROP_CLASSES, ex.CROP_COLORS)})
        dop = np.where(cls > 0, met["day_of_peak"], np.nan)
        vmax_d = float((dates[-1] - dates[0]).days)
        url = f"{base}/peak_day.webp"
        ex.save_png(ex.colorize_sequential(dop, 0, vmax_d), os.path.join(out_dir, url))
        overlays.append({"id": "peak", "name": "Date of peak canopy (HV max)", "url": url,
                         "legend": {"type": "sequential", "vmin": 0, "vmax": vmax_d, "unit": "days",
                                    "start_date": f"{dates[0]:%Y-%m-%d}",
                                    "ramp": ["#cde2fb", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"]}})
        areas = ch.class_areas(cls, pk, ch.CROP_CLASSES)
        stats += [{"label": a["label"], "value": a["area_km2"], "unit": "km²", "note": f"{a['pct']}% of imaged area"}
                  for a in areas]
        stats.append({"label": "Median HV dynamic range (rice)",
                      "value": round(float(np.nanmedian(met["dynamic_range_db"][cls == 1])), 1)
                      if (cls == 1).any() else 0, "unit": "dB", "note": "flood -> full canopy"})
        cube_src, cube_var = src, "HV" if hv is not None else "HH"
        ts_cls, names, class_colors = cls, ch.CROP_CLASSES, ex.CROP_COLORS
    else:
        raise ValueError(f"process_gcov cannot handle change_type={ct}")

    ser = ch.class_timeseries(cube_src, ts_cls, names)
    charts.append({"id": "backscatter", "title": f"Mean {cube_var} backscatter by class", "unit": "dB",
                   "kind": "line", "dates": [f"{d:%Y-%m-%d}" for d in dates],
                   "series": [{"name": s["name"], "values": s["values"],
                               "color": class_colors.get(s["code"], NEUTRAL)} for s in ser]})
    url = f"{base}/cube.json"
    ex.write_json(dict(ex.cube(cube_src, dates), var=cube_var, unit="dB"), os.path.join(out_dir, url))
    entry["layers"]["overlays"] = overlays
    entry["layers"]["cube"] = url
    entry["stats"] = stats
    entry["charts"] = charts
    entry["n_dates"] = T
    entry["date_range"] = [f"{dates[0]:%Y-%m-%d}", f"{dates[-1]:%Y-%m-%d}"]
    ex.write_json(entry, os.path.join(out_dir, base, "site.json"))
    return entry


# ================================================================ GUNW (earthquake)
def process_gunw_event(site, records, out_dir, max_px=900, demo=False):
    """records: interferograms of one track; those spanning the event are co-seismic.
    Others (if any) give the 'quiet' baseline in the pair-by-pair motion chart."""
    sid, base = site["id"], f"sites/{site['id']}"
    ev = _date(site["event_date"])
    sign = float(site.get("phase_sign", -1))
    records = sorted(records, key=lambda r: r["ref"])
    co = sorted([r for r in records if r["ref"] < ev < r["sec"]], key=lambda r: r["sec"] - r["ref"])
    if not co:
        raise RuntimeError("No interferogram spans the event date for this stack")
    main = co[0]

    def disp_of(r):
        d = r["data"]
        disp = insar.los_displacement(d["unwrappedPhase"], r["wavelength"], d.get("ionospherePhaseScreen"), sign)
        q = insar.quality_mask(d.get("coherenceMagnitude"), d.get("connectedComponents"))
        if q is not None:
            disp = np.where(q, disp, np.nan)
        rr = dict(r, data={"disp": disp, "coh": d.get("coherenceMagnitude", np.ones_like(disp))})
        web, b = _to_web(rr, "disp", site, max_px)
        coh, _ = _to_web(rr, "coh", site, max_px)
        return web, coh, b

    disp, coh, bounds = disp_of(main)
    ref_mask = insar.far_field_mask(disp.shape, (disp.shape[0] // 2, disp.shape[1] // 2), 0.12)
    disp = insar.reference(disp, ref_mask)
    cm = disp * 100
    vmax = float(np.nanpercentile(np.abs(cm), 99)) if np.isfinite(cm).any() else 10
    vmax = max(2.0, round(vmax))
    entry = _base_entry(site, bounds, demo)
    entry["stack"] = main.get("stack", {})
    overlays = []
    url = f"{base}/fringes.webp"
    ex.save_png(ex.colorize_cyclic(insar.rewrap(disp, main["wavelength"])), os.path.join(out_dir, url))
    overlays.append({"id": "fringes", "name": "Interferogram fringes (rewrapped)", "url": url, "default": True,
                     "legend": {"type": "cyclic", "period_cm": round(main["wavelength"] / 2 * 100, 1),
                                "note": "one colour cycle = λ/2 of line-of-sight motion"}})
    url = f"{base}/displacement.webp"
    ex.save_png(ex.colorize_diverging(cm, vmax, fade=False), os.path.join(out_dir, url))
    overlays.append({"id": "disp", "name": "Line-of-sight displacement", "url": url,
                     "legend": {"type": "diverging", "vmin": -vmax, "vmax": vmax, "unit": "cm",
                                "neg": ex.ORANGE, "pos": ex.BLUE, "mid": ex.MID_GRAY,
                                "neg_label": "away from satellite", "pos_label": "towards satellite"}})
    url = f"{base}/coherence.webp"
    ex.save_png(ex.colorize_sequential(coh, 0, 1), os.path.join(out_dir, url))
    overlays.append({"id": "coh", "name": "Interferometric coherence (data quality)", "url": url,
                     "legend": {"type": "sequential", "vmin": 0, "vmax": 1, "unit": "",
                                "ramp": ["#cde2fb", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"]}})
    entry["layers"]["frames"] = {"kind": "static", "items": []}
    entry["layers"]["overlays"] = overlays
    # pair-by-pair motion: p95 |LOS| per pair — the event pair spikes
    bars = []
    for r in records:
        d, _, _ = disp_of(r)
        d = insar.reference(d, ref_mask)
        bars.append({"label": f"{r['ref']:%d %b}–{r['sec']:%d %b}",
                     "value": round(float(np.nanpercentile(np.abs(d * 100), 95)), 2),
                     "event": bool(r["ref"] < ev < r["sec"])})
    entry["charts"] = [{"id": "pairs", "title": "Ground motion per 12-day pair (95th pct |LOS|)",
                        "unit": "cm", "kind": "bar", "bars": bars}]
    pk = _px_km2(site, disp.shape)
    # percentiles, not single pixels: at coherence ~0.3 the extreme pixel is unwrapping noise
    entry["stats"] = [
        {"label": "Peak motion towards satellite", "value": round(float(np.nanpercentile(cm, 99.5)), 1), "unit": "cm",
         "note": "99.5th percentile, line of sight"},
        {"label": "Peak motion away from satellite", "value": round(float(np.nanpercentile(cm, 0.5)), 1), "unit": "cm",
         "note": "0.5th percentile, line of sight"},
        {"label": "Area moved > 20 cm", "value": round(float((np.abs(cm) > 20).sum() * pk)), "unit": "km²",
         "note": "line of sight"},
        {"label": "Pair", "value": f"{main['ref']:%d %b} → {main['sec']:%d %b}", "unit": "",
         "note": f"{(main['sec'] - main['ref']).days}-day interferogram"}]
    url = f"{base}/cube.json"
    ex.write_json(dict(ex.cube(cm[None], [main["sec"]]), var="LOS", unit="cm"), os.path.join(out_dir, url))
    entry["layers"]["cube"] = url
    entry["date_range"] = [f"{main['ref']:%Y-%m-%d}", f"{main['sec']:%Y-%m-%d}"]
    ex.write_json(entry, os.path.join(out_dir, base, "site.json"))
    return entry


# ============================================================== GUNW (subsidence)
def process_gunw_series(site, records, out_dir, max_px=900, demo=False):
    sid, base = site["id"], f"sites/{site['id']}"
    sign = float(site.get("phase_sign", -1))
    records = sorted(records, key=lambda r: r["ref"])
    disps, bounds = [], None
    for r in records:
        d = r["data"]
        disp = insar.los_displacement(d["unwrappedPhase"], r["wavelength"], d.get("ionospherePhaseScreen"), sign)
        q = insar.quality_mask(d.get("coherenceMagnitude"), d.get("connectedComponents"), 0.25)
        if q is not None:
            disp = np.where(q, disp, np.nan)
        web, bounds = _to_web(dict(r, data={"disp": disp}), "disp", site, max_px)
        disps.append(web)
    # reference each pair to the stable area
    if site.get("reference_bbox"):
        w, s, e, n = site["bbox"]
        rw, rs, re_, rn = site["reference_bbox"]
        ny, nx = disps[0].shape
        lon = np.linspace(w, e, nx)
        lat = np.linspace(n, s, ny)
        ref = (lon[None] >= rw) & (lon[None] <= re_) & (lat[:, None] >= rs) & (lat[:, None] <= rn)
    else:
        ref = None
    disps = [insar.reference(d, ref) for d in disps]
    cum = insar.chain_pairs(disps)
    cm = np.stack(cum) * 100
    dates = [records[0]["ref"]] + [r["sec"] for r in records]
    cm = np.concatenate([np.zeros_like(cm[:1]), cm])
    vmax = max(2.0, round(float(np.nanpercentile(np.abs(cm[-1]), 99))))
    entry = _base_entry(site, bounds, demo)
    frames = []
    for i, d in enumerate(dates):
        url = f"{base}/frames/{d:%Y%m%d}.webp"
        ex.save_png(ex.colorize_diverging(cm[i], vmax, fade=False), os.path.join(out_dir, url))
        frames.append({"date": f"{d:%Y-%m-%d}", "url": url})
    leg = {"type": "diverging", "vmin": -vmax, "vmax": vmax, "unit": "cm", "neg": ex.ORANGE, "pos": ex.BLUE,
           "mid": ex.MID_GRAY, "neg_label": "away (subsiding)", "pos_label": "towards (uplift)"}
    entry["layers"]["frames"] = {"kind": "diverging", "legend": leg, "items": frames,
                                 "title": "Cumulative line-of-sight displacement"}
    entry["layers"]["overlays"] = []
    days = (dates[-1] - dates[0]).days or 1
    rate = cm[-1] / days * 365
    url = f"{base}/rate.webp"
    ex.save_png(ex.colorize_diverging(rate, max(5, round(float(np.nanpercentile(np.abs(rate), 99)))), fade=False),
                os.path.join(out_dir, url))
    rv = max(5, round(float(np.nanpercentile(np.abs(rate), 99))))
    entry["layers"]["overlays"].append({"id": "rate", "name": "Annualised LOS rate", "url": url,
                                        "legend": dict(leg, vmin=-rv, vmax=rv, unit="cm/yr")})
    flat = np.where(np.isfinite(cm[-1]), cm[-1], np.inf)
    iy, ix = np.unravel_index(np.argmin(flat), flat.shape)
    entry["charts"] = [{"id": "cum", "title": "Cumulative LOS displacement", "unit": "cm", "kind": "line",
                        "dates": [f"{d:%Y-%m-%d}" for d in dates],
                        "series": [{"name": "Fastest-sinking pixel", "color": ex.ORANGE,
                                    "values": [round(float(v), 2) for v in cm[:, iy, ix]]},
                                   {"name": "Area median", "color": NEUTRAL,
                                    "values": [round(float(np.nanmedian(f)), 2) for f in cm]}]}]
    pk = _px_km2(site, cm.shape[1:])
    entry["stats"] = [
        {"label": "Max subsidence (LOS)", "value": round(float(np.nanmin(cm[-1])), 1), "unit": "cm",
         "note": f"over {days} days"},
        {"label": "Peak rate", "value": round(float(np.nanmin(rate)), 1), "unit": "cm/yr", "note": "annualised"},
        {"label": "Area sinking > 1 cm/month", "value": round(float((rate < -12).sum() * pk)), "unit": "km²"},
        {"label": "Interferograms chained", "value": len(records), "unit": ""}]
    url = f"{base}/cube.json"
    ex.write_json(dict(ex.cube(cm, dates), var="LOS", unit="cm"), os.path.join(out_dir, url))
    entry["layers"]["cube"] = url
    entry["date_range"] = [f"{dates[0]:%Y-%m-%d}", f"{dates[-1]:%Y-%m-%d}"]
    ex.write_json(entry, os.path.join(out_dir, base, "site.json"))
    return entry


# ===================================================================== GOFF (ice)
def process_goff(site, records, out_dir, max_px=900, demo=False):
    sid, base = site["id"], f"sites/{site['id']}"
    records = sorted(records, key=lambda r: r["ref"])
    vels, bounds = [], None
    for r in records:
        d = r["data"]
        days = max((r["sec"] - r["ref"]).total_seconds() / 86400, 1e-3)
        v = insar.offsets_to_velocity(d["alongTrackOffset"], d["slantRangeOffset"], days, r.get("incidence"))
        if "snr" in d:
            v = np.where(d["snr"] > 5, v, np.nan)
        web, bounds = _to_web(dict(r, data={"v": v}), "v", site, max_px, method="bilinear")
        vels.append(web)
    V = np.stack(vels)
    vmax = max(1.0, round(float(np.nanpercentile(V, 99.5)), 0))
    entry = _base_entry(site, bounds, demo)
    frames = []
    for r, v in zip(records, V):
        url = f"{base}/frames/{r['sec']:%Y%m%d}.webp"
        ex.save_png(ex.colorize_sequential(v, 0, vmax), os.path.join(out_dir, url))
        frames.append({"date": f"{r['sec']:%Y-%m-%d}", "url": url})
    entry["layers"]["frames"] = {"kind": "sequential", "items": frames, "title": "Ice surface speed",
                                 "legend": {"type": "sequential", "vmin": 0, "vmax": vmax, "unit": "m/day",
                                            "ramp": ["#cde2fb", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"]}}
    entry["layers"]["overlays"] = []
    fast = np.nanmean(V, 0) > np.nanpercentile(V, 90)
    dates = [r["sec"] for r in records]
    entry["charts"] = [{"id": "speed", "title": "Ice speed through the melt season", "unit": "m/day",
                        "kind": "line", "dates": [f"{d:%Y-%m-%d}" for d in dates],
                        "series": [{"name": "Fast trunk (top 10%)", "color": ex.BLUE,
                                    "values": [round(float(np.nanmedian(v[fast])), 2) for v in V]},
                                   {"name": "Whole area median", "color": NEUTRAL,
                                    "values": [round(float(np.nanmedian(v)), 2) for v in V]}]}]
    sp = [float(np.nanmedian(v[fast])) for v in V]
    entry["stats"] = [
        {"label": "Peak trunk speed", "value": round(max(sp), 1), "unit": "m/day",
         "note": f"{dates[int(np.argmax(sp))]:%d %b}"},
        {"label": "≈ per year", "value": round(max(sp) * 365 / 1000, 1), "unit": "km/yr"},
        {"label": "Trunk speed range", "value": f"{min(sp):.1f}–{max(sp):.1f}", "unit": "m/day",
         "note": "12-day pairs; an isolated dip is usually tracking loss in melt, not a slowdown"},
        {"label": "Offset pairs", "value": len(records), "unit": ""}]
    url = f"{base}/cube.json"
    ex.write_json(dict(ex.cube(V, dates), var="speed", unit="m/day"), os.path.join(out_dir, url))
    entry["layers"]["cube"] = url
    entry["date_range"] = [f"{records[0]['ref']:%Y-%m-%d}", f"{dates[-1]:%Y-%m-%d}"]
    ex.write_json(entry, os.path.join(out_dir, base, "site.json"))
    return entry


PROCESSORS = {"flood": process_gcov, "wetland": process_gcov, "disturbance": process_gcov,
              "crop": process_gcov, "earthquake": process_gunw_event, "subsidence": process_gunw_series,
              "glacier": process_goff}


# ============================================================ fetching from ASF
def fetch_records(site, cache_dir, maturity="PROVISIONAL", max_frames=12, terms=("HHHH", "HVHV"), log=print,
                  multilook=3):
    """Search ASF, choose the best single-geometry stack, read bbox subsets (cached as .npz)."""
    from . import h5io, search

    product = site["product"]
    start, end = site["window"]
    res = search.search(site["bbox"], start, end, product, maturity)
    log(f"[{site['id']}] {len(res)} {product} granules found")
    if site["change_type"] == "earthquake":
        groups = search.stacks(res)
        ev = _date(site["event_date"])
        best = max(groups.values(), key=lambda g: (len(search.pairs_spanning(g, ev)) > 0, len(g)))
        stack = best
    else:
        stack = search.best_stack(res, site.get("prefer_direction"), site["bbox"])
        log(f"[{site['id']}] chosen stack covers {100 * search.coverage(stack, site['bbox']):.0f}% of the site box")
    stack = _subsample(stack, max_frames)
    if not stack:
        raise RuntimeError(f"No {product} data for {site['id']} — widen window/bbox or try maturity=BETA")
    g0 = stack[0]["granule"]
    info = {"track": g0.track, "frame": g0.frame, "direction": g0.direction, "band": g0.band, "n": len(stack)}
    log(f"[{site['id']}] stack track {g0.track} frame {g0.frame} {g0.direction}: {len(stack)} products")
    os.makedirs(os.path.join(cache_dir, site["id"]), exist_ok=True)
    recs = []
    for r in stack:
        cp = os.path.join(cache_dir, site["id"], r["name"] + ".npz")
        if os.path.exists(cp):
            rec = h5io.load_npz(cp)
        else:
            log(f"   reading {r['name']}")
            # Streaming one product takes minutes; the Earthdata session can expire mid-read
            # (401 on the URS redirect). A fresh open logs in again, so retry the product.
            for attempt in range(1, 4):
                try:
                    if product == "GCOV":
                        rec = h5io.multilook(h5io.read_gcov(r["url"], site["bbox"], terms), multilook)
                    elif product == "GUNW":
                        rec = h5io.read_gunw(r["url"], site["bbox"])
                    else:
                        rec = h5io.read_goff(r["url"], site["bbox"])
                    break
                except KeyError:
                    raise          # layer genuinely absent: retrying cannot help
                except Exception as e:
                    if attempt == 3:
                        raise
                    log(f"   attempt {attempt} failed ({type(e).__name__}: {str(e)[:80]}); retrying with a fresh session")
            h5io.save_npz(rec, cp)
        g = r["granule"]
        if product == "GCOV":
            rec["date"] = g.start
        else:
            rec["ref"], rec["sec"] = g.reference_secondary
        rec["stack"] = info
        rec["source"] = {"name": r["name"], "url": r["url"]}   # exact NASA granule, for provenance
        recs.append(rec)
    return recs


def run_site(site, out_dir, cache_dir, **kw):
    import shutil
    import tempfile

    recs = fetch_records(site, cache_dir, kw.get("maturity", "PROVISIONAL"), kw.get("max_frames", 12),
                         tuple(kw.get("terms", ("HHHH", "HVHV"))), multilook=kw.get("multilook", 3))
    # Build into a scratch dir, then swap the whole site folder: no stale (e.g. demo) frames
    # survive next to new ones, and a failed run leaves the published site untouched.
    tmp = tempfile.mkdtemp(prefix=f".build-{site['id']}-", dir=out_dir)
    try:
        entry = PROCESSORS[site["change_type"]](site, recs, tmp, kw.get("max_px", 900))
        # provenance for every product type: the stack and each NASA granule actually used
        entry["stack"] = entry.get("stack") or recs[0].get("stack", {})
        entry.setdefault("sources", [r["source"] for r in recs if r.get("source")])   # processors that drop dates set their own
        ex.write_json(entry, os.path.join(tmp, "sites", site["id"], "site.json"))
        dst = os.path.join(out_dir, "sites", site["id"])
        shutil.rmtree(dst, ignore_errors=True)
        shutil.move(os.path.join(tmp, "sites", site["id"]), dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return entry
