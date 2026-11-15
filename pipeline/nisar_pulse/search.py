"""Find NISAR products anywhere on Earth (ASF DAAC) and assemble comparable stacks.

    asf.search(dataset='NISAR', processingLevel='GCOV', dataMaturity='PROVISIONAL', ...)

Calibrated (PROVISIONAL) L-band products exist for acquisitions from 2026-06-17;
older BETA products are pre-calibration — fine for phase/geometry, not for dB values.
S-band products are distributed by ISRO's Bhoonidhi portal (separate account) — see
docs/DATA_ACCESS.md.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from . import granule as gr


def bbox_wkt(bbox) -> str:
    w, s, e, n = bbox
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def search(bbox, start, end, product="GCOV", maturity="PROVISIONAL", max_results=500) -> list[dict]:
    import asf_search as asf  # type: ignore

    kw = dict(dataset="NISAR", processingLevel=product, intersectsWith=bbox_wkt(bbox),
              start=start, end=end, maxResults=max_results)
    if maturity:
        kw["dataMaturity"] = maturity
    import time
    for attempt in range(5):   # CMR behind ASF search times out now and then; one slow reply shouldn't drop a site
        try:
            res = asf.search(**kw)
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(15 * (attempt + 1))
    out = []
    for r in res:
        p = r.properties
        name = p.get("fileID") or p.get("sceneName") or p.get("granuleName") or ""
        urls = r.get_urls() if hasattr(r, "get_urls") else [p.get("url")]
        h5 = [u for u in urls if u and u.endswith(".h5")] or urls
        try:
            g = gr.parse(name)
        except ValueError:
            continue
        out.append({"name": g.name, "url": h5[0], "granule": g,
                    "geometry": r.geometry, "bytes": p.get("bytes")})
    return out


def stacks(results: list[dict]) -> dict[tuple, list[dict]]:
    """Group by viewing geometry (band, product, track, direction, frame), sorted by time.
    Only images inside one group may be differenced — mixing geometries creates fake change."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        groups[r["granule"].stack_key].append(r)
    for k in groups:
        groups[k].sort(key=lambda r: r["granule"].start or datetime.min)
        # one product per acquisition DAY (pairs: per reference+secondary day): the same pass is
        # sometimes published twice (reprocessed CRID, or a 4005 and a 2005 mode cut); two copies
        # would double-count that date in every time series. Prefer dual-pol DH*, then newest CRID.
        def rank(r):
            g = r["granule"]
            return ((g.polarization or "").upper().startswith("DH"), g.crid or "")
        seen = {}
        for r in groups[k]:
            key = tuple(t.date() for t in r["granule"].times[:3])
            if key not in seen or rank(r) > rank(seen[key]):
                seen[key] = r
        groups[k] = sorted(seen.values(), key=lambda r: r["granule"].start or datetime.min)
    return dict(groups)


def coverage(results: list[dict], bbox) -> float:
    """Mean fraction of the site bbox covered by these products' footprints (0..1).
    1.0 when footprints are unknown, so missing geometry never disqualifies a stack."""
    if bbox is None:
        return 1.0
    from shapely.geometry import box, shape  # shapely ships with asf_search

    b = box(*bbox)
    vals = [shape(r["geometry"]).intersection(b).area / b.area for r in results if r.get("geometry")]
    return sum(vals) / len(vals) if vals else 1.0


def best_stack(results: list[dict], prefer_direction: str | None = None, bbox=None) -> list[dict]:
    """Most useful single-geometry stack: dates x bbox coverage (a 10-date stack that only
    clips 8% of the site loses to a 7-date stack that covers all of it)."""
    g = stacks(results)
    if not g:
        return []
    keys = sorted(g, key=lambda k: (k[3] == prefer_direction if prefer_direction else 0,
                                    len(g[k]) * coverage(g[k], bbox)), reverse=True)
    return g[keys[0]]


def pairs_spanning(results: list[dict], event: datetime) -> list[dict]:
    """Interferograms whose reference is before and secondary after the event (co-seismic),
    shortest temporal baseline first (least decorrelation, least post-seismic contamination)."""
    out = []
    for r in results:
        ref, sec = r["granule"].reference_secondary
        if ref and sec and ref < event < sec:
            out.append((sec - ref, r))
    return [r for _, r in sorted(out, key=lambda t: t[0])]
