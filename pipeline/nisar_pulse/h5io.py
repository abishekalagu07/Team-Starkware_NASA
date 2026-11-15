"""Read and spatially subset NISAR HDF5 products — local files or streamed over HTTPS/S3.

Design choice: **path discovery instead of hard-coded paths.** NISAR products follow
the layout ``/science/<LSAR|SSAR>/<PRODUCT>/grids/frequency<A|B>/...`` but layer
names nest differently between products (e.g. GUNW keeps its rasters under
``unwrappedInterferogram/<POL>/``) and CRIDs may move things. We walk the file once
and look datasets up by *leaf name*, so the same code reads L-band (ASF) and
S-band (Bhoonidhi) products and survives minor spec revisions.

Verify on day one with:  ``python -m nisar_pulse inspect <file-or-url>``
"""
from __future__ import annotations

import io
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from . import geo

C_LIGHT = 299_792_458.0
DEFAULT_WAVELENGTH = {"L": 0.2384, "S": 0.0937}  # m (1.2575 GHz, 3.2 GHz)


def _h5py():
    try:
        import h5py  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install h5py  (see pipeline/requirements.txt)") from e
    return h5py


# --------------------------------------------------------------------- opening
class HTTPRangeFile(io.RawIOBase):
    """Read-only, seekable file over HTTP range requests, for h5py.

    Why not fsspec/aiohttp: streaming one product takes minutes, and ASF's Earthdata
    session can expire mid-read. The data host then redirects to URS OAuth, which
    aiohttp cannot answer (401). `requests` re-authenticates on that redirect from
    ~/.netrc (or _netrc) / EARTHDATA_USERNAME+PASSWORD and keeps the cookies, so reads
    simply continue. Blocks are LRU-cached; network errors are retried with backoff.
    """

    def __init__(self, url: str, block: int = 4 << 20, cache_blocks: int = 32, retries: int = 6):
        import requests  # type: ignore

        self.url, self.block, self.max, self.retries, self.pos = url, block, cache_blocks, retries, 0
        self.s = requests.Session()
        if os.getenv("EARTHDATA_USERNAME"):
            self.s.auth = (os.environ["EARTHDATA_USERNAME"], os.environ["EARTHDATA_PASSWORD"])
        self.cache: OrderedDict[int, bytes] = OrderedDict()
        self.size = int(self._get(0, 0)[1].split("/")[-1])

    def _get(self, a: int, b: int) -> tuple[bytes, str]:
        import requests  # type: ignore

        err = None
        for attempt in range(self.retries):
            try:
                with self.s.get(self.url, headers={"Range": f"bytes={a}-{b}"}, timeout=60, stream=True) as r:   # 4 MB; 60 s is already slow
                    if r.status_code == 206:   # never accept a 200: that would be the whole multi-GB file
                        return r.content, r.headers.get("Content-Range", "")
                    err = f"HTTP {r.status_code} from {r.url[:80]}"
            except requests.RequestException as e:
                err = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 5 * 2 ** attempt))
        raise OSError(f"range {a}-{b} of {self.url} failed after {self.retries} tries: {err}")

    def _blk(self, i: int) -> bytes:
        if i in self.cache:
            self.cache.move_to_end(i)
            return self.cache[i]
        a = i * self.block
        data = self._get(a, min(a + self.block, self.size) - 1)[0]
        self.cache[i] = data
        if len(self.cache) > self.max:
            self.cache.popitem(last=False)
        return data

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else min(n, self.size - self.pos)
        out = bytearray()
        while len(out) < max(0, n):
            i, o = divmod(self.pos + len(out), self.block)
            out += self._blk(i)[o:o + n - len(out)]
        self.pos += len(out)
        return bytes(out)

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def open_product(src: str):
    """Open a NISAR product.

    * local path            -> h5py.File
    * https://... (ASF)     -> HTTPRangeFile (Earthdata Login from ~/.netrc or EARTHDATA_USERNAME/PASSWORD)
    * s3://... (in-region)  -> earthaccess S3 credentials (only from AWS us-west-2)
    Only the chunks covering your bbox are fetched, so a 2 GB GCOV costs ~MBs.
    """
    h5py = _h5py()
    if src.startswith(("http://", "https://")):
        return h5py.File(HTTPRangeFile(src), "r")
    if src.startswith("s3://"):
        import earthaccess  # type: ignore

        earthaccess.login(strategy="environment" if os.getenv("EARTHDATA_USERNAME") else "netrc")
        return h5py.File(earthaccess.open([src])[0], "r")
    return h5py.File(src, "r")


# ------------------------------------------------------------------- discovery
def walk(f) -> dict[str, tuple]:
    out: dict[str, tuple] = {}

    def visit(name, obj):
        if hasattr(obj, "shape"):
            out["/" + name] = (obj.shape, str(obj.dtype))

    f.visititems(visit)
    return out


def find(index: dict, leaf: str, contains: str | tuple = (), exclude: str | tuple = ()) -> str | None:
    contains = (contains,) if isinstance(contains, str) else contains
    exclude = (exclude,) if isinstance(exclude, str) else exclude
    hits = [p for p in index if p.rsplit("/", 1)[-1] == leaf
            and all(c in p for c in contains) and not any(x in p for x in exclude)]
    return sorted(hits, key=len)[0] if hits else None


def _scalar(f, path):
    if path is None or path not in f:
        return None
    v = f[path][()]
    if isinstance(v, bytes):
        return v.decode()
    if isinstance(v, np.ndarray):
        if v.dtype.kind in "SO":
            return [x.decode() if isinstance(x, bytes) else x for x in v.ravel()]
        return v.tolist() if v.size > 1 else v.item()
    return v.item() if hasattr(v, "item") else v


def identification(f, index=None) -> dict:
    index = index or walk(f)
    keys = ["trackNumber", "frameNumber", "orbitPassDirection", "zeroDopplerStartTime",
            "zeroDopplerEndTime", "referenceZeroDopplerStartTime", "secondaryZeroDopplerStartTime",
            "listOfFrequencies", "productType", "lookDirection", "productVersion", "missionId",
            "granuleId", "isUrgentObservation"]
    meta = {}
    for k in keys:
        p = find(index, k, "identification")
        if p:
            meta[k] = _scalar(f, p)
    meta["band"] = "S" if any("/SSAR/" in p for p in index) else "L"
    return meta


def _epsg(f, group: str, index: dict) -> int | None:
    p = find(index, "projection", group) or find(index, "projection")
    if p is None:
        return None
    ds = f[p]
    for a in ("epsg_code", "epsg", "EPSG"):
        if a in ds.attrs:
            return int(np.asarray(ds.attrs[a]).ravel()[0])
    try:
        return int(ds[()])
    except Exception:
        return None


@dataclass
class Grid:
    x: np.ndarray
    y: np.ndarray
    epsg: int
    window: tuple[slice, slice] = field(default=(slice(None), slice(None)))

    @property
    def dx(self):
        return float(self.x[1] - self.x[0])

    @property
    def dy(self):
        return float(self.y[1] - self.y[0])


def grid_for(f, layer_path: str, index: dict, bbox=None, pad_px: int = 2) -> Grid:
    """Find the x/y coordinate vectors that belong to ``layer_path`` (closest
    ancestor that has xCoordinates) and compute the bbox read window."""
    parent = layer_path.rsplit("/", 1)[0]
    xp = None
    while parent:
        cand = parent + "/xCoordinates"
        if cand in index:
            xp = cand
            break
        parent = parent.rsplit("/", 1)[0]
    if xp is None:
        raise KeyError(f"No xCoordinates above {layer_path}")
    yp = xp.replace("xCoordinates", "yCoordinates")
    x = f[xp][()]
    y = f[yp][()]
    epsg = _epsg(f, parent, index)
    if epsg is None:
        raise KeyError("projection/EPSG not found — pass epsg manually")
    if bbox is None:
        return Grid(x, y, epsg)
    xmin, ymin, xmax, ymax = geo.bbox_to_xy_window(bbox, epsg)
    ix = np.where((x >= xmin) & (x <= xmax))[0]
    iy = np.where((y >= ymin) & (y <= ymax))[0]
    if ix.size == 0 or iy.size == 0:
        raise ValueError("bbox does not intersect this product")
    sx = slice(max(ix.min() - pad_px, 0), min(ix.max() + pad_px + 1, len(x)))
    sy = slice(max(iy.min() - pad_px, 0), min(iy.max() + pad_px + 1, len(y)))
    return Grid(x[sx], y[sy], epsg, (sy, sx))


def _read(f, path, win, fill_to_nan=True):
    ds = f[path]
    a = ds[win]
    if fill_to_nan and a.dtype.kind == "f":
        fv = ds.attrs.get("_FillValue")
        if fv is not None:
            a = np.where(a == np.asarray(fv).ravel()[0], np.nan, a)
    return a


def _freq_tag(freq: str) -> str:
    return f"frequency{freq}"


# --------------------------------------------------------------------- readers
def read_gcov(src, bbox=None, terms=("HHHH", "HVHV"), freq="A") -> dict:
    """Return linear-power gamma0 (RTC) covariance diagonals for a bbox.

    Missing terms (e.g. VVVV in an HH/HV acquisition) are skipped, not errors.
    """
    with open_product(src) as f:
        idx = walk(f)
        meta = identification(f, idx)
        found = {t: find(idx, t, ("GCOV", _freq_tag(freq))) for t in terms}
        found = {t: p for t, p in found.items() if p}
        if not found:
            raise KeyError(f"None of {terms} in {src}. Available: "
                           f"{sorted({p.rsplit('/', 1)[-1] for p in idx if _freq_tag(freq) in p})}")
        g = grid_for(f, next(iter(found.values())), idx, bbox)
        data = {}
        for t, p in found.items():
            a = _read(f, p, g.window).astype("f4")
            a[~np.isfinite(a) | (a <= 0)] = np.nan
            data[t] = a
        # numberOfLooks varies slowly across a frame: a 64x64 sample at the window centre gives
        # the same median as the whole window for a fraction of the download. (The GCOV mask
        # layer was read here too but never used downstream, so it is no longer fetched.)
        nl = find(idx, "numberOfLooks", ("GCOV", _freq_tag(freq)))
        looks = None
        if nl:
            ds, (rs, cs) = f[nl], g.window
            r0 = ((rs.start or 0) + (rs.stop or ds.shape[0])) // 2
            c0 = ((cs.start or 0) + (cs.stop or ds.shape[1])) // 2
            with np.errstate(all="ignore"):
                v = float(np.nanmedian(ds[r0:r0 + 64, c0:c0 + 64]))
            looks = v if np.isfinite(v) and v > 0 else None   # centre can fall in no-data
    return {"kind": "GCOV", "data": data, "x": g.x, "y": g.y, "epsg": g.epsg,
            "mask": None, "looks": looks, "meta": meta, "src": str(src)}


def multilook(rec: dict, n: int) -> dict:
    """n x n block mean of a GCOV record (linear power, so averaging is physically right),
    with x/y moved to block centres. Cuts speckle and cache size by n^2; the web layers
    are far coarser than 10 m anyway. Equivalent looks grow by n^2."""
    if n <= 1:
        return rec
    import warnings

    def block(a):
        r, c = a.shape[0] // n * n, a.shape[1] // n * n
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)   # all-NaN blocks stay NaN
            return np.nanmean(a[:r, :c].reshape(r // n, n, c // n, n), axis=(1, 3)).astype("f4")

    out = dict(rec)
    out["data"] = {k: block(v) for k, v in rec["data"].items() if v is not None}
    nx, ny = len(rec["x"]) // n * n, len(rec["y"]) // n * n
    out["x"] = np.asarray(rec["x"][:nx]).reshape(-1, n).mean(1)
    out["y"] = np.asarray(rec["y"][:ny]).reshape(-1, n).mean(1)
    lk = rec.get("looks")
    out["looks"] = (lk if lk and np.isfinite(lk) else 4.0) * n * n
    return out


def read_gunw(src, bbox=None, pol="HH", freq="A") -> dict:
    """Unwrapped phase (rad), coherence, connected components, iono screen + wavelength."""
    with open_product(src) as f:
        idx = walk(f)
        meta = identification(f, idx)
        base = ("GUNW", _freq_tag(freq), "unwrappedInterferogram")
        phase_p = find(idx, "unwrappedPhase", base + (pol,)) or find(idx, "unwrappedPhase", base)
        if phase_p is None:
            raise KeyError("unwrappedPhase not found — run `inspect` and update h5io.read_gunw")
        g = grid_for(f, phase_p, idx, bbox)
        sub = phase_p.rsplit("/", 1)[0]

        def layer(name):
            p = sub + "/" + name if (sub + "/" + name) in idx else find(idx, name, base)
            return _read(f, p, g.window).astype("f4") if p else None

        out = {
            "unwrappedPhase": layer("unwrappedPhase"),
            "coherenceMagnitude": layer("coherenceMagnitude"),
            "connectedComponents": layer("connectedComponents"),
            "ionospherePhaseScreen": layer("ionospherePhaseScreen"),
        }
        cf = find(idx, "centerFrequency", _freq_tag(freq))
        wl = C_LIGHT / float(_scalar(f, cf)) if cf else DEFAULT_WAVELENGTH[meta["band"]]
    return {"kind": "GUNW", "data": out, "x": g.x, "y": g.y, "epsg": g.epsg,
            "wavelength": wl, "meta": meta, "src": str(src)}


def read_goff(src, bbox=None, freq="A", layer_hint="layer1") -> dict:
    """Pixel-offset product: along-track / slant-range offsets (m) for glacier & landslide motion."""
    with open_product(src) as f:
        idx = walk(f)
        meta = identification(f, idx)
        base = ("GOFF", _freq_tag(freq))
        az = find(idx, "alongTrackOffset", base + (layer_hint,)) or find(idx, "alongTrackOffset", base)
        rg = find(idx, "slantRangeOffset", base + (layer_hint,)) or find(idx, "slantRangeOffset", base)
        if az is None or rg is None:
            raise KeyError("offset layers not found — run `inspect` and update h5io.read_goff")
        g = grid_for(f, az, idx, bbox)
        data = {"alongTrackOffset": _read(f, az, g.window).astype("f4"),
                "slantRangeOffset": _read(f, rg, g.window).astype("f4")}
        snr = find(idx, "snr", base)
        if snr:
            data["snr"] = _read(f, snr, g.window).astype("f4")
    return {"kind": "GOFF", "data": data, "x": g.x, "y": g.y, "epsg": g.epsg, "meta": meta, "src": str(src)}


def inspect(src, max_lines: int = 400) -> str:
    with open_product(src) as f:
        idx = walk(f)
        meta = identification(f, idx)
    lines = [f"{p}  {s}  {d}" for p, (s, d) in sorted(idx.items())]
    head = "\n".join(f"{k}: {v}" for k, v in meta.items())
    return head + "\n" + "\n".join(lines[:max_lines])


# ------------------------------------------------------------------ caching
def save_npz(rec: dict, path: str):
    flat = {f"data__{k}": v for k, v in rec["data"].items() if v is not None}
    np.savez_compressed(path, x=rec["x"], y=rec["y"], epsg=rec["epsg"],
                        meta=np.array(json.dumps(rec.get("meta", {}), default=str)),
                        wavelength=rec.get("wavelength", np.nan), kind=rec["kind"],
                        looks=rec.get("looks") or np.nan, **flat)


def load_npz(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    data = {k[6:]: z[k] for k in z.files if k.startswith("data__")}
    return {"kind": str(z["kind"]), "data": data, "x": z["x"], "y": z["y"], "epsg": int(z["epsg"]),
            "wavelength": float(z["wavelength"]), "meta": json.loads(str(z["meta"])),
            "looks": (float(z["looks"]) if "looks" in z.files and np.isfinite(z["looks"]) else None)}
