"""Render analysis arrays into web-ready layers + catalog.

Every raster is resampled to a Web-Mercator-aligned lon/lat grid (geo.regrid_to_webmercator)
so the browser can drape it as an image overlay with four corner coordinates — no tile
server needed, the whole product can be hosted on GitHub Pages. COGs are also written
(when rasterio is installed) for GIS users / reproducibility.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import date, datetime, timezone

import numpy as np

# Palette (validated categorical + diverging poles; see web/README for the rationale)
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
NAVY, MID_GRAY = "#104281", "#d9d8d4"

FLOOD_COLORS = {1: NAVY, 2: BLUE, 3: YELLOW, 4: AQUA}
DISTURB_COLORS = {1: RED, 2: GREEN}
CROP_COLORS = {1: AQUA, 2: YELLOW}


def _hex(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype="f4")


def colorize_gray(db, vmin=-25.0, vmax=0.0):
    v = np.clip((np.asarray(db, "f4") - vmin) / (vmax - vmin), 0, 1)
    out = np.zeros(v.shape + (4,), np.uint8)
    g = np.nan_to_num(v * 255).astype(np.uint8)
    out[..., 0] = out[..., 1] = out[..., 2] = g
    out[..., 3] = np.isfinite(db) * 255
    return out


def colorize_diverging(v, vmax, neg=ORANGE, pos=BLUE, mid=MID_GRAY, fade=True, fade_at=0.25):
    """Two-hue diverging with a neutral midpoint. With ``fade`` the near-zero values
    become transparent so the basemap stays readable and only real change pops."""
    v = np.asarray(v, "f4")
    t = np.clip(v / vmax, -1, 1)
    a = np.abs(t)[..., None]
    pole = np.where((t < 0)[..., None], _hex(neg), _hex(pos))
    rgb = _hex(mid) * (1 - a) + pole * a
    out = np.zeros(v.shape + (4,), np.uint8)
    out[..., :3] = np.nan_to_num(rgb).astype(np.uint8)
    alpha = np.clip(np.abs(t) / fade_at, 0, 1) if fade else np.ones_like(t)
    out[..., 3] = (np.nan_to_num(alpha) * 235 * np.isfinite(v)).astype(np.uint8)
    return out


def colorize_sequential(v, vmin, vmax, ramp=("#cde2fb", "#6da7ec", "#2a78d6", "#184f95", "#0d366b")):
    v = np.asarray(v, "f4")
    t = np.clip((v - vmin) / (vmax - vmin), 0, 1)
    stops = np.stack([_hex(h) for h in ramp])
    pos = np.nan_to_num(t) * (len(ramp) - 1)
    i0 = np.floor(pos).astype(int).clip(0, len(ramp) - 2)
    f = (pos - i0)[..., None]
    rgb = stops[i0] * (1 - f) + stops[i0 + 1] * f
    out = np.zeros(v.shape + (4,), np.uint8)
    out[..., :3] = rgb.astype(np.uint8)
    out[..., 3] = np.isfinite(v) * 230
    return out


def colorize_cyclic(frac):
    """Wrapped fringes (0..1). Cyclic maps are the domain standard for wrapped phase."""
    import matplotlib

    cmap = matplotlib.colormaps["twilight_shifted"]
    f = np.asarray(frac, "f4")
    rgba = (cmap(np.nan_to_num(f)) * 255).astype(np.uint8)
    rgba[..., 3] = np.isfinite(f) * 230
    return rgba


def colorize_classes(cls, colors: dict, alpha=215):
    cls = np.asarray(cls)
    out = np.zeros(cls.shape + (4,), np.uint8)
    for k, h in colors.items():
        m = cls == k
        out[m, :3] = _hex(h).astype(np.uint8)
        out[m, 3] = alpha
    return out


def save_png(rgba, path):
    from PIL import Image

    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = Image.fromarray(rgba, "RGBA")
    if path.endswith(".webp"):  # continuous imagery: ~10x smaller than PNG, alpha kept
        im.save(path, "WEBP", quality=82, method=4)
    else:  # class maps: lossless keeps crisp class edges & exact colours
        im.save(path, optimize=True)
    return path


def write_cog(arr, bounds, path, nodata=np.nan):
    """GeoTIFF (COG layout) in EPSG:4326 of a web-grid array. Skipped silently without rasterio."""
    try:
        import rasterio
        from rasterio.transform import from_bounds
    except ImportError:
        return None
    w, s, e, n = bounds
    ny, nx = arr.shape
    # web grid rows are uniform in mercator, not latitude; for small AOIs the
    # difference is sub-pixel. For strict work write in EPSG:3857 instead.
    prof = dict(driver="GTiff", height=ny, width=nx, count=1, dtype="float32", crs="EPSG:4326",
                transform=from_bounds(w, s, e, n, nx, ny), nodata=nodata, tiled=True,
                blockxsize=256, blockysize=256, compress="deflate")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr.astype("f4"), 1)
    return path


def cube(stack, dates, max_side=64, scale=10):
    """Coarse (T, ny, nx) cube for click-anywhere time series in the browser.
    Values stored as rounded ints (value*scale) with null for NaN to keep JSON small."""
    T, ny, nx = stack.shape
    fy, fx = max(1, int(np.ceil(ny / max_side))), max(1, int(np.ceil(nx / max_side)))
    cy, cx = ny // fy, nx // fx
    s = stack[:, :cy * fy, :cx * fx].reshape(T, cy, fy, cx, fx)
    import warnings

    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        m = np.nanmean(s, axis=(2, 4))
    data = [[[None if not np.isfinite(v) else int(round(v * scale)) for v in row] for row in fr] for fr in m]
    return {"dates": [_iso(d) for d in dates], "shape": [cy, cx], "scale": scale, "data": data}


def _iso(d):
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    return str(d)


def write_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"), default=_iso)
    return path


def build_catalog(web_data_dir: str, demo: bool = False) -> str:
    """Merge every sites/<id>/site.json into data/catalog.json (what the web app loads)."""
    sites = []
    for p in sorted(glob.glob(os.path.join(web_data_dir, "sites", "*", "site.json"))):
        with open(p) as fh:
            sites.append(json.load(fh))
    cat = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "demo": demo or any(s.get("demo") for s in sites), "sites": sites}
    return write_json(cat, os.path.join(web_data_dir, "catalog.json"))
