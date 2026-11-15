"""Generate a physically-plausible SYNTHETIC dataset for every showcase site.

Why: the web team can build the whole UI in hour 0 while the data team pulls real
NISAR products, and CI can test the full pipeline offline. Synthetic records go
through exactly the same ``workflows.process_*`` code as real ones.

Everything produced here is flagged ``demo: true`` and the web app shows a
"SYNTHETIC DEMO DATA" banner. Never present these images as NISAR observations.

    python scripts/make_demo_data.py            # writes ../web/data
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import numpy as np
from scipy.ndimage import gaussian_filter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nisar_pulse import export, geo, workflows  # noqa: E402
from nisar_pulse.cli import CONFIG, WEB_DATA, load_sites  # noqa: E402
from nisar_pulse.sar import from_db  # noqa: E402

RNG = np.random.default_rng(42)
L_WAVE = 0.2384


def grid(site, spacing):
    w, s, e, n = site["bbox"]
    lat_c, lon_c = (s + n) / 2, (w + e) / 2
    epsg = 3413 if lat_c > 60 else (3031 if lat_c < -60 else geo.utm_zone_epsg(lon_c, lat_c))
    xmin, ymin, xmax, ymax = geo.bbox_to_xy_window(site["bbox"], epsg)
    x = np.arange(xmin, xmax, spacing) + spacing / 2
    y = np.arange(ymax, ymin, -spacing) - spacing / 2  # north-up like NISAR grids
    X, Y = np.meshgrid(x, y)
    lon, lat = geo.xy_to_lonlat(X, Y, epsg)
    return x, y, epsg, lon, lat


def smooth_noise(shape, sigma, rng=RNG):
    f = gaussian_filter(rng.standard_normal(shape), sigma)
    return (f - f.mean()) / (f.std() + 1e-9)


def speckle(lin, looks=6, rng=RNG):
    return (lin * rng.gamma(looks, 1 / looks, lin.shape)).astype("f4")


def dates12(start="2026-06-20", n=12):
    d0 = datetime.fromisoformat(start)
    return [d0 + timedelta(days=12 * i) for i in range(n)]


# ------------------------------------------------------------------- flood / wetland
def demo_flood(site, papyrus=False):
    x, y, epsg, lon, lat = grid(site, 60)
    sh = lon.shape
    yy, xx = np.indices(sh)
    # sinuous river roughly W->E (Brahmaputra) / S->N (White Nile)
    if papyrus:
        centre = sh[1] / 2 + 0.12 * sh[1] * np.sin(yy / sh[0] * 5) + 15 * smooth_noise(sh, 30)
        dist = np.abs(xx - centre)
    else:
        centre = sh[0] / 2 + 0.15 * sh[0] * np.sin(xx / sh[1] * 7) + 10 * smooth_noise(sh, 40)
        dist = np.abs(yy - centre)
    elev = dist / max(sh) * 40 + 3 * smooth_noise(sh, 25)  # metres above river
    forest = smooth_noise(sh, 12) > (0.2 if papyrus else 0.9)  # trees / papyrus stands
    river = dist < (0.03 * max(sh))
    dates = dates12()
    ev = datetime.fromisoformat(site["event_date"])
    recs = []
    for d in dates:
        dt = (d - ev).days
        level = 0.4 + (9.0 if not papyrus else 7.0) * np.exp(-((dt - 22) / 28.0) ** 2) * (dt > -12)
        wet = (elev < level) | river
        hh = np.full(sh, -9.0) + 1.5 * smooth_noise(sh, 3)
        hv = np.full(sh, -16.0) + 1.5 * smooth_noise(sh, 3)
        hh[forest] = -7.0
        hv[forest] = -12.0
        ow = wet & ~forest
        fv = wet & forest & ~river
        hh[ow], hv[ow] = -23.0, -29.0
        hh[fv], hv[fv] = -1.5, -11.0  # double bounce brightens HH only
        hh[river], hv[river] = -25.0, -30.0
        rec = {"date": d, "x": x, "y": y, "epsg": epsg, "looks": 6,
               "data": {"HHHH": speckle(from_db(hh)), "HVHV": speckle(from_db(hv))}}
        recs.append(rec)
    return recs


# ------------------------------------------------------------------- disturbance
def demo_disturbance(site, kind="fire"):
    x, y, epsg, lon, lat = grid(site, 60)
    sh = lon.shape
    yy, xx = np.indices(sh)
    forest = smooth_noise(sh, 15) > (-0.6 if kind != "grass" else 2)
    dates = dates12()
    ev = datetime.fromisoformat(site["event_date"])
    recs = []
    if kind == "fire":
        cy, cx = sh[0] * 0.45, sh[1] * 0.5
        r_noise = 0.25 * smooth_noise(sh, 20)
        r = np.hypot((yy - cy) / sh[0], (xx - cx) / sh[1]) * (1 + r_noise)
    else:  # fishbone deforestation along a N-S road
        road = np.abs(xx - sh[1] * 0.5 - 20 * np.sin(yy / 60)) < 2
        side = (np.abs(xx - sh[1] * 0.5) < sh[1] * 0.35) & ((yy // 25) % 3 == 0)
        order = RNG.random(sh[0] // 25 + 1)[yy // 25] + np.abs(xx - sh[1] * 0.5) / sh[1]
    for d in dates:
        dt = (d - ev).days
        hh = -7.5 + 1.2 * smooth_noise(sh, 3)
        hv = -12.5 + 1.2 * smooth_noise(sh, 3)
        hh = np.where(forest, hh, -11.0)
        hv = np.where(forest, hv, -19.0)
        if kind == "fire":
            radius = 0 if dt < 0 else min(0.32, 0.06 + 0.012 * dt)
            burnt = r < radius
        else:
            burnt = (side | road) & (order < max(0, dt) / 90.0)
        hv = np.where(burnt & forest, -18.0 + smooth_noise(sh, 2), hv)
        hh = np.where(burnt & forest, -9.5 + smooth_noise(sh, 2), hh)
        recs.append({"date": d, "x": x, "y": y, "epsg": epsg, "looks": 6,
                     "data": {"HHHH": speckle(from_db(hh)), "HVHV": speckle(from_db(hv))}})
    return recs


# ------------------------------------------------------------------- crop
def demo_crop(site):
    x, y, epsg, lon, lat = grid(site, 40)
    sh = lon.shape
    yy, xx = np.indices(sh)
    fid = (yy // 18) * 10_000 + (xx // 25)  # rectangular parcels ~0.7 x 1 km
    ids = np.unique(fid)
    ftype = dict(zip(ids, RNG.choice([1, 2, 0], ids.size, p=[0.62, 0.25, 0.13])))
    t0 = dict(zip(ids, RNG.integers(5, 40, ids.size)))  # transplant day after 20 Jun
    T = np.vectorize(ftype.get)(fid)
    D = np.vectorize(t0.get)(fid)
    town = smooth_noise(sh, 30) > 1.6
    dates = dates12(n=12)
    recs = []
    for d in dates:
        day = (d - dates[0]).days
        g = 1 / (1 + np.exp(-(day - D - 35) / 8))  # canopy growth
        harvest = day > D + 115
        hv = np.where(T == 1, -19 + 8 * g, -20 + 5 / (1 + np.exp(-(day - 40) / 12)))
        hh = np.where(T == 1, -12 + 3 * g, -11 + 2 / (1 + np.exp(-(day - 40) / 12)))
        flooded = (T == 1) & (day >= D) & (day < D + 18)
        hv = np.where(flooded, -27, hv)
        hh = np.where(flooded, -21, hh)
        hv = np.where((T == 1) & harvest, -19.5, hv)
        hh = np.where((T == 1) & harvest, -11.5, hh)
        hv = np.where(T == 0, -17, hv)
        hh = np.where(T == 0, -10, hh)
        hv = np.where(town, -8, hv)
        hh = np.where(town, 0, hh)
        recs.append({"date": d, "x": x, "y": y, "epsg": epsg, "looks": 6,
                     "data": {"HHHH": speckle(from_db(hh + smooth_noise(sh, 1))),
                              "HVHV": speckle(from_db(hv + smooth_noise(sh, 1)))}})
    return recs


# ------------------------------------------------------------------- earthquake
def demo_quake(site):
    x, y, epsg, lon, lat = grid(site, 80)
    sh = lon.shape
    (lo1, la1), (lo2, la2) = site["epicenters"]
    # fault trace through both epicentres; distance (km) perpendicular to it
    v = np.array([lo2 - lo1, la2 - la1]) * [111 * np.cos(np.radians(la1)), 111]
    v /= np.linalg.norm(v)
    px = (lon - lo1) * 111 * np.cos(np.radians(la1))
    py = (lat - la1) * 111
    along = px * v[0] + py * v[1]
    perp = -px * v[1] + py * v[0]
    L = np.hypot(*((np.array([lo2 - lo1, la2 - la1]) * [111 * np.cos(np.radians(la1)), 111])))
    taper = np.clip(1 - np.maximum(np.maximum(-along - 25, along - L - 25), 0) / 40, 0, 1)
    slip, depth = 3.2, 14.0
    # right-lateral screw dislocation (m), decaying away from a finite-length rupture
    u_par = (slip / np.pi) * np.arctan(perp / depth) * taper * np.exp(-np.abs(perp) / 35.0)
    u_e, u_n = u_par * v[0], u_par * v[1]
    inc, head = np.radians(37), np.radians(-12)  # ascending, left-looking
    le, ln, lu = np.sin(inc) * np.cos(head), -np.sin(inc) * np.sin(head), np.cos(inc)
    los = u_e * le + u_n * ln + 0.04 * np.exp(-(perp / 6) ** 2) * taper * lu
    d0 = datetime(2026, 6, 8, 10, 30)
    recs = []
    for k in range(5):
        ref, sec = d0 + timedelta(days=12 * k), d0 + timedelta(days=12 * (k + 1))
        spans = ref < datetime(2026, 6, 24, 22, 4) < sec
        disp = (los if spans else 0.004 * smooth_noise(sh, 20)) + 0.006 * smooth_noise(sh, 40)
        iono = 2.0 * smooth_noise(sh, 120)
        phase = -4 * np.pi / L_WAVE * disp + iono
        coh = np.clip(0.75 + 0.15 * smooth_noise(sh, 6) - (0.5 * np.exp(-(perp / 2.5) ** 2) * taper if spans else 0),
                      0.05, 1)
        recs.append({"ref": ref, "sec": sec, "x": x, "y": y, "epsg": epsg, "wavelength": L_WAVE,
                     "data": {"unwrappedPhase": phase.astype("f4"), "ionospherePhaseScreen": iono.astype("f4"),
                              "coherenceMagnitude": coh.astype("f4"),
                              "connectedComponents": np.ones(sh, "f4")}})
    return recs


def demo_subsidence(site):
    x, y, epsg, lon, lat = grid(site, 80)
    sh = lon.shape
    bowl = (np.exp(-(((lon + 99.03) / 0.07) ** 2 + ((lat - 19.37) / 0.06) ** 2))
            + 0.6 * np.exp(-(((lon + 99.10) / 0.04) ** 2 + ((lat - 19.46) / 0.035) ** 2)))
    rate = -0.38 * bowl  # m / yr
    d0 = datetime(2026, 6, 20, 0, 50)
    recs = []
    for k in range(11):
        ref, sec = d0 + timedelta(days=12 * k), d0 + timedelta(days=12 * (k + 1))
        disp = rate * 12 / 365 + 0.004 * smooth_noise(sh, 25)
        phase = -4 * np.pi / L_WAVE * disp
        coh = np.clip(0.8 + 0.1 * smooth_noise(sh, 4), 0.05, 1)
        recs.append({"ref": ref, "sec": sec, "x": x, "y": y, "epsg": epsg, "wavelength": L_WAVE,
                     "data": {"unwrappedPhase": phase.astype("f4"), "coherenceMagnitude": coh.astype("f4"),
                              "connectedComponents": np.ones(sh, "f4")}})
    return recs


def demo_glacier(site):
    x, y, epsg, lon, lat = grid(site, 150)
    sh = lon.shape
    centre = 69.17 + 0.02 * np.sin((lon + 50.4) * 4)
    across = np.abs(lat - centre) / 0.03
    along = np.clip((lon + 48.8) / -1.6, 0, 1)  # 0 inland -> 1 at front
    channel = np.exp(-across**2)
    rock = (np.abs(lat - centre) > 0.08)
    base = 0.6 + 38 * channel * along**2.5
    d0 = datetime(2026, 6, 20)
    recs = []
    for k in range(11):
        ref, sec = d0 + timedelta(days=12 * k), d0 + timedelta(days=12 * (k + 1))
        season = 1 + 0.18 * np.exp(-(((sec - datetime(2026, 7, 25)).days) / 25) ** 2) - 0.08 * (k / 10)
        v = np.where(rock, 0.02, base * season) + 0.2 * smooth_noise(sh, 2)
        ang = np.radians(35)
        off = v * 12
        recs.append({"ref": ref, "sec": sec, "x": x, "y": y, "epsg": epsg,
                     "data": {"alongTrackOffset": (off * np.cos(ang)).astype("f4"),
                              "slantRangeOffset": (off * np.sin(ang)).astype("f4"),
                              "snr": np.full(sh, 20.0, "f4")}})
    return recs


def main():
    d, sites = load_sites(CONFIG)
    builders = {
        "assam-brahmaputra": lambda s: demo_flood(s),
        "sudd-wetland": lambda s: demo_flood(s, papyrus=True),
        "punjab-paddy": demo_crop,
        "rowe-creek-fire": lambda s: demo_disturbance(s, "fire"),
        "huelva-fire": lambda s: demo_disturbance(s, "fire"),
        "amazon-br163": lambda s: demo_disturbance(s, "clearing"),
        "venezuela-doublet": demo_quake,
        "mexico-city": demo_subsidence,
        "sermeq-kujalleq": demo_glacier,
    }
    for sid, s in sites.items():
        recs = builders[sid](s)
        for r in recs:
            r["stack"] = {"track": 0, "frame": 0, "direction": "A", "band": "L", "n": len(recs), "synthetic": True}
        workflows.PROCESSORS[s["change_type"]](s, recs, WEB_DATA, max_px=d.get("max_px", 900) // 1, demo=True)
        print("demo ->", sid)
    print(export.build_catalog(WEB_DATA, demo=True))


if __name__ == "__main__":
    main()
