# NISAR Earth Pulse 🌍📡

**An open-source explorer of Earth's surface change as seen by the NASA–ISRO NISAR radar.**
It covers floods, flooded forests, wildfires, deforestation, rice seasons, earthquakes, sinking cities and
racing glaciers, each explained by the physics of how a radar pulse interacts with the ground.

**Live app:** https://abishekalagu07.github.io/Team-Starkware_NASA/ · **Team Starkware**, NASA Space Apps Challenge 2026

> Global by design, curated by necessity. **Explore anywhere** queries the live ASF archive for any
> box you drag on Earth and gives you the one-line command that processes it. The **showcase sites**
> cover every kind of change across five continents, pre-processed into time-lapses, change maps and dashboards.

| Site | Change | Product | Signal |
|---|---|---|---|
| Brahmaputra, Assam 🇮🇳 | flood | GCOV | HH drop (open water) + HH rise (flooded vegetation) |
| Sudd wetland 🇸🇸 | wetland | GCOV | papyrus double bounce |
| Punjab paddy belt 🇮🇳 | agriculture | GCOV | HV flood→growth curve (radar crop calendar) |
| Rowe Creek fire 🇺🇸 · Huelva fire 🇪🇸 | wildfire | GCOV | persistent HV loss |
| BR-163, Pará 🇧🇷 | deforestation | GCOV | HV loss, fishbone clearings |
| Venezuela M7.2+M7.5 🇻🇪 | earthquake | GUNW | co-seismic fringes, 11.9 cm per cycle |
| Mexico City 🇲🇽 | subsidence | GUNW chain | cumulative LOS, cm/yr |
| Sermeq Kujalleq 🇬🇱 | glacier | GOFF | ice speed every 12 days |

## Features

* **Change-detection maps.** Flood classes (including the L-band flooded-vegetation class), burn and clearing maps,
  crop type from phenology, LOS displacement, ice speed.
* **Time-lapse.** Play, step, scrub. Class maps follow the acquisition date.
* **Swipe compare.** Before vs after, on synchronised maps.
* **Dashboard.** Headline numbers, area-over-time charts, mean backscatter per class, and
  **click anywhere for that pixel's time series**. Every chart has a table view.
* **"What am I seeing?"** Plain-language physics, likely drivers and caveats for each site.
* **Explore anywhere.** Live NISAR search for any rectangle on Earth, grouped into comparable stacks
  (same track, frame and direction), with links to ASF Vertex and Bhoonidhi.
* Basemaps: dark map, or Sentinel-2 cloudless for optical context. Globe view.
* **Hosting.** Fully static (GitHub Pages). No tile server, because overlays are pre-warped to Web-Mercator-aligned images.

## Quick start

Every layer in the app is processed from NISAR products published by NASA (ASF DAAC).
You need a free [Earthdata Login](https://urs.earthdata.nasa.gov) to download them.

```bash
# 1. pipeline
cd pipeline
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt     # (Linux/macOS: .venv/bin/pip)
python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"   # saves ~/.netrc (_netrc on Windows)

# 2. process the showcase sites (only each site's bbox is streamed out of the multi-GB files)
export NISAR_CACHE=/path/with/space          # optional: where bbox subsets are cached (default pipeline/cache)
python -m nisar_pulse run --all               # or: run --site huelva-fire   (hours; re-runs are instant from cache)

# 3. web app
cd ../web && python -m http.server 8000       # open http://localhost:8000

# any place on Earth
python -m nisar_pulse search --bbox 93.6 26.55 94.7 27.15 --start 2026-06-17 --end 2026-10-31 --product GCOV
python -m nisar_pulse inspect <one granule URL>           # print the HDF5 layout
python -m nisar_pulse adhoc --bbox W S E N --type flood --start 2026-07-01 --end 2026-09-30
python -m pytest -q tests                                  # offline unit tests
```

`scripts/make_demo_data.py` produces synthetic layers for offline development of the web UI only;
they are tagged *Simulated* in the app and are not part of the published showcase.

## Architecture

```
ASF DAAC (L-band) / Bhoonidhi (S-band)
   │  asf_search / earthaccess — stream only the bbox chunks of each HDF5
   ▼
pipeline/nisar_pulse
   granule.py   parse names → group by band/track/frame/direction (never mix geometries)
   h5io.py      path-discovery readers for GCOV / GUNW / GOFF (+ inspect)
   sar.py       dB↔linear, Lee filter, RVI, dual-pol false colour (fixed stretch)
   change.py    Otsu water, flood/flooded-veg classes, persistent HV loss, rice phenology
   insar.py     phase→LOS, iono removal, coherence masking, fringes, asc/desc → east/up, offsets→speed
   geo.py       UTM / polar-stereo (pyproj optional) + Web-Mercator-aligned regridding
   export.py    WebP/PNG overlays, COGs, time-series cubes, catalog.json
   workflows.py one recipe per change type (same code for real & synthetic data)
   ▼
web/ (static)  MapLibre GL · vanilla JS · dependency-free SVG charts
```

## Repository

```
pipeline/   Python package, config/sites.yaml, scripts/make_demo_data.py, tests/
web/        index.html, css/, js/ (app, charts, explore), data/ (generated)
docs/       PLAN_12H.md · DATA_ACCESS.md · SCIENCE.md
.github/    CI: tests + GitHub Pages deploy of web/
```

## Honesty notes

* NISAR PROVISIONAL products are calibrated but only partially validated; see the NISAR Data User Guide's known issues.
* Site coordinates marked `verify` in `sites.yaml` come from news and agency reports. Refine them with official perimeters.
* Each site's dashboard lists the exact NASA granules it was built from (with ASF download links), the track/frame/direction of the stack, and how much of the site box that stack covers.
* Change classes are radar-derived: an HV drop means canopy volume was lost, not *why* (fire vs. harvest). Pair with FIRMS / EFFIS / gauge data before attributing a cause.

## Credits

NISAR is a joint mission of NASA and ISRO. L-band data: ASF DAAC. S-band data: ISRO/NRSC Bhoonidhi.
Basemaps: Esri World Dark Gray Canvas (Esri, HERE, Garmin, © OpenStreetMap contributors); Sentinel-2 cloudless by EOX.
License: MIT.
