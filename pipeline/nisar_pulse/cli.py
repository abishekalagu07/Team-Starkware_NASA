"""Command line.

  python -m nisar_pulse inspect <file.h5|https-url>          # print HDF5 tree + identification
  python -m nisar_pulse search  --bbox W S E N --start 2026-07-01 --end 2026-09-01 --product GCOV
  python -m nisar_pulse run     --site assam-brahmaputra       # one showcase site
  python -m nisar_pulse run     --all                          # every site in config/sites.yaml
  python -m nisar_pulse adhoc   --bbox W S E N --type flood --start ... --end ... [--event ...]
  python -m nisar_pulse catalog                                # rebuild web/data/catalog.json
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WEB_DATA = os.path.join(ROOT, "web", "data")
CACHE = os.getenv("NISAR_CACHE") or os.path.join(ROOT, "pipeline", "cache")   # set to a roomy drive
CONFIG = os.path.join(ROOT, "pipeline", "config", "sites.yaml")

PRODUCT_FOR = {"flood": "GCOV", "wetland": "GCOV", "disturbance": "GCOV", "crop": "GCOV",
               "earthquake": "GUNW", "subsidence": "GUNW", "glacier": "GOFF"}


def load_sites(path=CONFIG):
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    d = cfg.get("defaults", {})
    return d, {s["id"]: s for s in cfg["sites"]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="nisar_pulse")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("src")
    p = sub.add_parser("search")
    p.add_argument("--bbox", nargs=4, type=float, required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--product", default="GCOV")
    p.add_argument("--maturity", default="PROVISIONAL")
    p = sub.add_parser("run")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--site")
    g.add_argument("--all", action="store_true")
    p.add_argument("--maturity")
    p.add_argument("--max-frames", type=int)
    p = sub.add_parser("adhoc", help="process any bbox on Earth")
    p.add_argument("--bbox", nargs=4, type=float, required=True)
    p.add_argument("--type", required=True, choices=sorted(PRODUCT_FOR))
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--event")
    p.add_argument("--name", default="Custom area")
    p.add_argument("--id", default="custom")
    sub.add_parser("catalog")
    a = ap.parse_args(argv)

    if a.cmd == "inspect":
        from . import h5io

        print(h5io.inspect(a.src))
    elif a.cmd == "search":
        from . import search

        res = search.search(a.bbox, a.start, a.end, a.product, a.maturity or None)
        for key, items in sorted(search.stacks(res).items(), key=lambda kv: -len(kv[1])):
            band, prod, track, direc, frame = key
            print(f"{band}-band {prod} track {track} frame {frame} {direc}: {len(items)} products")
            for r in items:
                print("   ", r["name"])
    elif a.cmd in ("run", "adhoc"):
        from . import export, workflows

        d, sites = load_sites()
        if a.cmd == "adhoc":
            todo = [{"id": a.id, "name": a.name, "region": "", "continent": "", "change_type": a.type,
                     "product": PRODUCT_FOR[a.type], "bbox": a.bbox, "window": [a.start, a.end],
                     "event_date": a.event, "story": {"headline": a.name}}]
            if not a.event:
                todo[0].pop("event_date")
        else:
            todo = list(sites.values()) if a.all else [sites[a.site]]
        ok = 0
        for s in todo:
            try:
                workflows.run_site(s, WEB_DATA, CACHE, maturity=getattr(a, "maturity", None) or d.get("maturity"),
                                   max_frames=getattr(a, "max_frames", None) or d.get("max_frames", 12),
                                   max_px=d.get("max_px", 900), terms=d.get("terms", ["HHHH", "HVHV"]))
                ok += 1
                print(f"[{s['id']}] done")
            except Exception as e:  # keep going: one bad site must not kill a 12-hour run
                print(f"[{s['id']}] FAILED: {e}", file=sys.stderr)
                traceback.print_exc()
        print("catalog ->", export.build_catalog(WEB_DATA))
        print(f"{ok}/{len(todo)} sites processed")
    elif a.cmd == "catalog":
        from . import export

        print(export.build_catalog(WEB_DATA))
    return 0


if __name__ == "__main__":
    sys.exit(main())
