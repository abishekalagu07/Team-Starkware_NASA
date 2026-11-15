# 12-hour execution plan: 4 people, 1 submission

**Goal:** a deployed, open-source web app showing real NISAR change at 6–9 sites (every kind
of change, every continent we can reach), an "explore anywhere" mode that works for the whole
Earth, a 2–3 minute demo video and a clean README.

The code here already runs end to end on synthetic data. Your 12 hours go into **real data,
validation and storytelling**, not scaffolding.

## Roles

| Person | Owns | Sites / deliverables |
|---|---|---|
| **A: SAR backscatter lead** | `GCOV` pipeline, `change.py` thresholds | Assam flood, Sudd wetland, Punjab paddy, Rowe Creek fire, Huelva fire, Amazon BR-163 |
| **B: InSAR & ice lead** | `GUNW` / `GOFF`, sign convention, ionosphere | Venezuela doublet, Mexico City, Sermeq Kujalleq; stretch: ascending + descending → east/up |
| **C: Frontend lead** | `web/`, GitHub Pages deploy, performance, accessibility | swipe, time-lapse, dashboard polish, mobile, explore-anywhere |
| **D: Science & story lead** | `docs/SCIENCE.md`, site stories, validation, video, slides | context layers (FIRMS, GPM, WorldCover), sanity checks, final pitch |

## Timeline

| Hour | A (backscatter) | B (InSAR/ice) | C (frontend) | D (story) |
|---|---|---|---|---|
| **0:00–0:45** | Earthdata login + `.netrc`. `pip install -r requirements.txt`. `make_demo_data.py` works | same; request a Bhoonidhi account (S-band) | serve `web/` locally on demo data; create the GitHub repo + Pages | read SCIENCE.md; confirm site bboxes vs. NIFC/EFFIS/USGS (marked `verify`) |
| **0:45–1:30** | `search` each GCOV site → pick the stack with most dates; `inspect` one file and **confirm HDF5 paths** | `search` GUNW over Venezuela: is there a pair spanning 24 Jun? `inspect` one GUNW + one GOFF | deploy demo to Pages (CI is ready) | write the 1-sentence story + “why radar” for each site |
| **1:30–4:00** | `run --site assam-brahmaputra` (first real site) → push → visible in app. Then Punjab, Sudd | Venezuela GUNW → **validate sign** vs USGS finite-fault / expected polarity. Then Mexico City chain | layer UX, legend, dashboard on real data; fix whatever real data breaks | pull FIRMS fire points, GPM rainfall for Assam as validation; screenshots |
| **4:00** | ✅ **Checkpoint 1:** ≥2 real sites live in deployed app | | | |
| **4:00–7:00** | 3 disturbance sites; tune `drop_db`, `persist` | glacier GOFF; check SNR mask; stretch: asc/desc decomposition for Venezuela | explore-anywhere tested on 5 continents; mobile layout; loading states | draft video script; label every chart with physics |
| **7:00** | ✅ **Checkpoint 2:** all sites real (or explicitly flagged as demo) | | | |
| **7:00–9:00** | S-band vs L-band comparison panel for Assam/Punjab (if Bhoonidhi data arrived) | write the "accuracy & limits" section | performance (WebP sizes, preload), a11y pass (table views, contrast) | record demo video (screen capture of deployed app) |
| **9:00** | 🧊 **Feature freeze** | | | |
| **9:00–11:00** | re-run all sites clean from cache; tag release | review numbers in stats tiles vs. sources | bug bash on 3 browsers; README GIF | edit video; slides; submission text |
| **11:00–12:00** | buffer | buffer | final deploy | submit; double-check links work logged-out |

## Rules that save hackathons

1. **Cache everything.** `pipeline/cache/*.npz` holds every subset you read, so re-runs take seconds. Never re-download.
2. **Never mix viewing geometries.** `search.best_stack` enforces one band/track/frame/direction per stack.
3. **Average in linear power, show in dB.**
4. **Run where the data is.** On an AWS VM in **us-west-2**, `earthaccess` reads the ASF S3 bucket directly, often 10× faster than HTTPS from elsewhere.
5. **Demo data must stay labelled.** The app shows a banner whenever any site has `demo: true`. Replace demo sites with real ones, or keep them labelled; never present synthetic images as NISAR.
6. **A failed site never blocks others.** `run --all` continues past errors and rebuilds the catalog.

## Risk register

| Risk | Signal | Fallback |
|---|---|---|
| No calibrated product over a site | `search` returns 0 | widen window, `--maturity BETA` (phase OK, dB not calibrated), or swap to another site of the same change type |
| HDF5 layer names differ | `KeyError` from `h5io` | `inspect`, then adjust the leaf name in `h5io.read_*` (paths are discovered by leaf name, so it is usually a one-word fix) |
| Streaming too slow | > 2 min per product | shrink bbox; run in us-west-2; download whole files with `results.download()` overnight-style in background |
| Interferogram sign flipped | uplift shows as subsidence | `phase_sign: 1` in `sites.yaml` |
| Ionosphere ramps (equator, poles) | long-wavelength gradients | ionosphere screen is subtracted by default; additionally remove a planar ramp |
| Fire site shows nothing | grass/shrub fuels | physics: little volume to lose at L-band; say so and pick a forest fire |
