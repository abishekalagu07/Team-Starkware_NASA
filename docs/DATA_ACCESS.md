# Getting NISAR data

## L-band (NASA, global): ASF DAAC

* Account: free **NASA Earthdata Login**: https://urs.earthdata.nasa.gov
* Put credentials in `~/.netrc` (`machine urs.earthdata.nasa.gov login USER password PASS`)
  or export `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD`.
* Browse: ASF Vertex https://search.asf.alaska.edu (dataset NISAR) or NASA Earthdata Search.
* Docs: NISAR Data User Guide https://nisar-docs.asf.alaska.edu

Data maturity:

| maturity | what | use for |
|---|---|---|
| `PROVISIONAL` | calibrated, partially validated; acquisitions from **2026-06-17** | backscatter (dB) change, InSAR |
| `BETA` | pre-calibration products from Oct 2025 – Jan 2026 (subset) | geometry/phase only; do not compare dB with PROVISIONAL |

Products used here:

| product | level | what | change types |
|---|---|---|---|
| `GCOV` | L2 | RTC gamma0 covariance (HHHH, HVHV, …), 10–20 m | flood, wetland, fire, deforestation, crops |
| `GUNW` | L2 | unwrapped interferogram (80 m) + coherence, connected components, ionosphere screen; 12-day nearest-neighbour co-pol pairs | earthquakes, subsidence |
| `GOFF` | L2 | geocoded pixel offsets | glaciers, large landslides |
| `SME2` | L3 | soil moisture | (stretch) |

```bash
python -m nisar_pulse search --bbox 93.6 26.55 94.7 27.15 --start 2026-06-17 --end 2026-10-31 --product GCOV
python -m nisar_pulse inspect "https://…/NISAR_L2_PR_GCOV_….h5"   # streamed, prints the HDF5 tree
python -m nisar_pulse run --site assam-brahmaputra
python -m nisar_pulse adhoc --bbox W S E N --type flood --start 2026-07-01 --end 2026-09-30 --event 2026-07-20
```

Only the HDF5 chunks covering your bbox are fetched when streaming, so a multi-GB granule
usually costs tens of MB.

## S-band (ISRO): Bhoonidhi

* Portal: https://bhoonidhi.nrsc.gov.in (NISAR page: https://bhoonidhi.nrsc.gov.in/NISAR)
* Registration required (allow time for approval: do it in hour 0).
* Coverage: the Indian landmass plus selected global science sites; RSLC/GSLC/GCOV and
  interferometric/offset products. File names follow the same `NISAR_S…` pattern, and the
  same `h5io` readers work (they look up `/science/SSAR/…` automatically).
* Use: Assam and Punjab dual-frequency comparison. S-band (~9 cm) responds to leaves and the upper
  canopy, while L-band (~24 cm) reaches stems, trunks and the ground.

## Context / validation layers (optional, all free)

| layer | why | where |
|---|---|---|
| Sentinel-2 / HLS optical | "what it looks like" vs radar | Earthdata Search (HLS), Copernicus |
| NASA FIRMS active fires | validate burn maps | https://firms.modaps.eosdis.nasa.gov |
| GPM IMERG rainfall | explain flood timing | Earthdata Search |
| ESA WorldCover 10 m | land cover per change class | https://esa-worldcover.org |
| USGS earthquake finite-fault | validate InSAR sign & pattern | https://earthquake.usgs.gov |
| WorldPop | people exposed to change | https://www.worldpop.org |
| RADARSAT-1 archive (CSA), SAOCOM L-band (CONAE) | multi-sensor / long-term context | see challenge resources |
