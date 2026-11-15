"""Geodesy helpers with zero hard dependencies.

NISAR L2 products are posted on UTM grids (and polar-stereographic grids near the
poles: EPSG:3413 Arctic, EPSG:3031 Antarctic). For a hackathon we want:

  * lon/lat bbox  -> product grid indices (to stream only the pixels we need)
  * product grid  -> a Web-Mercator-aligned lon/lat image the browser can drape

pyproj is used when installed; otherwise the closed-form Snyder (USGS PP1395)
series below are accurate to well below a pixel (< 1 m) inside a UTM zone.
"""
from __future__ import annotations

import math

import numpy as np

A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)
E = math.sqrt(E2)
EP2 = E2 / (1 - E2)
K0 = 0.9996

try:  # optional fast path
    from pyproj import Transformer  # type: ignore

    _HAVE_PYPROJ = True
except Exception:  # pragma: no cover
    _HAVE_PYPROJ = False


# ----------------------------------------------------------------------------- UTM
def utm_zone_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def _utm_params(epsg: int) -> tuple[float, bool]:
    zone = epsg % 100
    south = 32700 < epsg < 32800
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    return lon0, south


def _utm_fwd(lon, lat, epsg):
    lon0, south = _utm_params(epsg)
    phi = np.radians(lat)
    lam = np.radians(lon)
    n = A / np.sqrt(1 - E2 * np.sin(phi) ** 2)
    t = np.tan(phi) ** 2
    c = EP2 * np.cos(phi) ** 2
    a_ = (lam - lon0) * np.cos(phi)
    e4, e6 = E2**2, E2**3
    m = A * (
        (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * phi)
        - (35 * e6 / 3072) * np.sin(6 * phi)
    )
    x = K0 * n * (a_ + (1 - t + c) * a_**3 / 6 + (5 - 18 * t + t**2 + 72 * c - 58 * EP2) * a_**5 / 120) + 500000.0
    y = K0 * (
        m
        + n * np.tan(phi) * (a_**2 / 2 + (5 - t + 9 * c + 4 * c**2) * a_**4 / 24
                             + (61 - 58 * t + t**2 + 600 * c - 330 * EP2) * a_**6 / 720)
    )
    if south:
        y = y + 10_000_000.0
    return x, y


def _utm_inv(x, y, epsg):
    lon0, south = _utm_params(epsg)
    x = np.asarray(x, dtype="f8") - 500000.0
    y = np.asarray(y, dtype="f8") - (10_000_000.0 if south else 0.0)
    e4, e6 = E2**2, E2**3
    m = y / K0
    mu = m / (A * (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * np.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * np.sin(4 * mu)
            + (151 * e1**3 / 96) * np.sin(6 * mu)
            + (1097 * e1**4 / 512) * np.sin(8 * mu))
    c1 = EP2 * np.cos(phi1) ** 2
    t1 = np.tan(phi1) ** 2
    n1 = A / np.sqrt(1 - E2 * np.sin(phi1) ** 2)
    r1 = A * (1 - E2) / (1 - E2 * np.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * K0)
    phi = phi1 - (n1 * np.tan(phi1) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * EP2 - 3 * c1**2) * d**6 / 720
    )
    lam = lon0 + (d - (1 + 2 * t1 + c1) * d**3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * EP2 + 24 * t1**2) * d**5 / 120) / np.cos(phi1)
    return np.degrees(lam), np.degrees(phi)


# ------------------------------------------------------------- polar stereographic
_POLAR = {3413: (70.0, -45.0, False), 3031: (-71.0, 0.0, True)}  # lat_ts, lon0, south


def _ps_t(phi):
    return np.tan(np.pi / 4 - phi / 2) / ((1 - E * np.sin(phi)) / (1 + E * np.sin(phi))) ** (E / 2)


def _ps_consts(epsg):
    lat_ts, lon0, south = _POLAR[epsg]
    phic = math.radians(abs(lat_ts))
    mc = math.cos(phic) / math.sqrt(1 - E2 * math.sin(phic) ** 2)
    tc = float(_ps_t(np.array(phic)))
    return math.radians(lon0), south, mc, tc


def _ps_fwd(lon, lat, epsg):
    lon0, south, mc, tc = _ps_consts(epsg)
    phi = np.radians(lat)
    lam = np.radians(lon)
    if south:
        phi, lam, lon0 = -phi, -lam, -lon0
    rho = A * mc * _ps_t(phi) / tc
    x = rho * np.sin(lam - lon0)
    y = -rho * np.cos(lam - lon0)
    if south:
        x, y = -x, -y
    return x, y


def _ps_inv(x, y, epsg):
    lon0, south, mc, tc = _ps_consts(epsg)
    x = np.asarray(x, dtype="f8")
    y = np.asarray(y, dtype="f8")
    if south:
        x, y, lon0 = -x, -y, -lon0
    rho = np.hypot(x, y)
    t = rho * tc / (A * mc)
    chi = np.pi / 2 - 2 * np.arctan(t)
    e4, e6, e8 = E2**2, E2**3, E2**4
    phi = (chi + (E2 / 2 + 5 * e4 / 24 + e6 / 12 + 13 * e8 / 360) * np.sin(2 * chi)
           + (7 * e4 / 48 + 29 * e6 / 240 + 811 * e8 / 11520) * np.sin(4 * chi)
           + (7 * e6 / 120 + 81 * e8 / 1120) * np.sin(6 * chi)
           + (4279 * e8 / 161280) * np.sin(8 * chi))
    lam = lon0 + np.arctan2(x, -y)
    if south:
        phi, lam = -phi, -lam
    lon = (np.degrees(lam) + 180) % 360 - 180
    return lon, np.degrees(phi)


# ------------------------------------------------------------------ public API
def lonlat_to_xy(lon, lat, epsg: int):
    lon = np.asarray(lon, dtype="f8")
    lat = np.asarray(lat, dtype="f8")
    if epsg == 4326:
        return lon, lat
    if _HAVE_PYPROJ:
        tr = Transformer.from_crs(4326, epsg, always_xy=True)
        return tr.transform(lon, lat)
    if 32601 <= epsg <= 32760:
        return _utm_fwd(lon, lat, epsg)
    if epsg in _POLAR:
        return _ps_fwd(lon, lat, epsg)
    raise NotImplementedError(f"EPSG:{epsg} needs pyproj (pip install pyproj)")


def xy_to_lonlat(x, y, epsg: int):
    x = np.asarray(x, dtype="f8")
    y = np.asarray(y, dtype="f8")
    if epsg == 4326:
        return x, y
    if _HAVE_PYPROJ:
        tr = Transformer.from_crs(epsg, 4326, always_xy=True)
        return tr.transform(x, y)
    if 32601 <= epsg <= 32760:
        return _utm_inv(x, y, epsg)
    if epsg in _POLAR:
        return _ps_inv(x, y, epsg)
    raise NotImplementedError(f"EPSG:{epsg} needs pyproj (pip install pyproj)")


def bbox_to_xy_window(bbox, epsg: int, densify: int = 21):
    """lon/lat bbox (W,S,E,N) -> (xmin, ymin, xmax, ymax) in the product CRS.

    The bbox edge is densified so the projected window fully contains it.
    """
    w, s, e, n = bbox
    t = np.linspace(0, 1, densify)
    lons = np.concatenate([w + (e - w) * t, np.full(densify, e), e - (e - w) * t, np.full(densify, w)])
    lats = np.concatenate([np.full(densify, s), s + (n - s) * t, np.full(densify, n), n - (n - s) * t])
    x, y = lonlat_to_xy(lons, lats, epsg)
    return float(np.min(x)), float(np.min(y)), float(np.max(x)), float(np.max(y))


# --------------------------------------------------- Web-Mercator-aligned regrid
def _merc_y(lat):
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def _inv_merc_y(my):
    return np.degrees(2 * np.arctan(np.exp(my)) - np.pi / 2)


def regrid_to_webmercator(arr, x, y, epsg: int, bbox=None, max_px: int = 1024, method="nearest"):
    """Resample a projected raster onto a grid that is uniform in lon and in
    Web-Mercator northing, so it drapes *exactly* as a MapLibre/Leaflet image
    overlay given its four lon/lat corners.

    arr : (ny, nx) or (k, ny, nx); x, y : 1-D pixel-centre coordinates.
    Returns (out, bounds) with bounds = (west, south, east, north).
    """
    x = np.asarray(x, dtype="f8")
    y = np.asarray(y, dtype="f8")
    if bbox is None:
        xx = np.array([x[0], x[-1], x[0], x[-1]])
        yy = np.array([y[0], y[0], y[-1], y[-1]])
        lo, la = xy_to_lonlat(xx, yy, epsg)
        bbox = (float(lo.min()), float(la.min()), float(lo.max()), float(la.max()))
    w, s, e, n = bbox
    dx = abs(x[1] - x[0]) if len(x) > 1 else 1.0
    # pick output size from native pixel size (approx metres per degree)
    lat_c = (s + n) / 2
    nx_native = (e - w) * 111_320 * math.cos(math.radians(lat_c)) / dx
    ny_native = (n - s) * 110_540 / dx
    scale = min(1.0, max_px / max(nx_native, ny_native, 1))
    nx_o = max(2, int(round(nx_native * scale)))
    ny_o = max(2, int(round(ny_native * scale)))
    lons = np.linspace(w, e, nx_o)
    my = np.linspace(_merc_y(n), _merc_y(s), ny_o)  # top row = north
    lats = _inv_merc_y(my)
    LON, LAT = np.meshgrid(lons, lats)
    X, Y = lonlat_to_xy(LON, LAT, epsg)
    # fractional pixel indices on the source grid (regular 1-D axes)
    fx = (X - x[0]) / (x[1] - x[0])
    fy = (Y - y[0]) / (y[1] - y[0])
    stack = arr if arr.ndim == 3 else arr[None]
    out = np.full((stack.shape[0], ny_o, nx_o), np.nan, dtype="f4")
    if method == "bilinear":
        from scipy.ndimage import map_coordinates

        for k in range(stack.shape[0]):
            out[k] = map_coordinates(stack[k].astype("f4"), [fy, fx], order=1, cval=np.nan)
    else:
        ix = np.rint(fx).astype(int)
        iy = np.rint(fy).astype(int)
        ok = (ix >= 0) & (ix < len(x)) & (iy >= 0) & (iy < len(y))
        for k in range(stack.shape[0]):
            out[k][ok] = stack[k][iy[ok], ix[ok]]
    return (out if arr.ndim == 3 else out[0]), (w, s, e, n)


def pixel_area_km2(dx: float, dy: float) -> float:
    return abs(dx * dy) / 1e6
