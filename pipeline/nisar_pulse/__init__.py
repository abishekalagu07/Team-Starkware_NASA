"""NISAR Earth Pulse — turn NISAR L-/S-band radar products into surface-change stories.

Modules
-------
granule   : parse NISAR file names (track, frame, direction, polarisation, dates)
search    : find NISAR products anywhere on Earth via ASF (asf_search)
h5io      : read & spatially subset NISAR HDF5 products (GCOV, GUNW, GOFF) — local or streamed
geo       : dependency-free WGS84 <-> UTM / polar-stereo transforms and lat/lon regridding
sar       : radiometry helpers (dB, multilook, speckle filters, polarimetric indices)
change    : change detection (log-ratio, z-score, Otsu water, flood / burn / crop classifiers)
insar     : interferometric phase -> line-of-sight displacement
export    : PNG overlays, COGs, time-series cubes, catalog.json for the web app
workflows : end-to-end per-site recipes
"""

__version__ = "0.1.0"
