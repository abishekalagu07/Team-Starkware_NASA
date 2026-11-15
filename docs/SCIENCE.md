# The science behind each layer

## 1. What the radar measures

NISAR emits microwave pulses and records the echo:
* **L-band**, λ ≈ 24 cm (NASA/JPL)
* **S-band**, λ ≈ 9 cm (ISRO)

It images nearly all land and ice twice every 12 days, day or night, through cloud and smoke.
Two properties set how bright a pixel is:

* **Roughness and geometry, relative to λ.** Smooth surfaces mirror energy away (dark). Rough surfaces scatter
  it back. Vertical structures standing on flat ground form a corner reflector, which is very bright.
* **Dielectric constant.** Water raises it sharply, so wet soil is brighter than dry soil, and calm open water
  is the exception: it is a mirror, so it looks dark.

The phase of the echo is measured to a fraction of λ. Comparing two passes (**interferometry**) reveals
centimetre-scale ground motion.

## 2. Scattering mechanisms and polarisations

| mechanism | where | strongest in |
|---|---|---|
| surface (single bounce) | bare soil, roads, rough water | HH / VV |
| volume | canopies, crops, snow/firn | **HV** (cross-pol) |
| double bounce | buildings, **water under trees/crops** | **HH** |

**HV is the vegetation channel. HH is the water-under-vegetation channel.**

## 3. Methods and their hypotheses

### Floods & wetlands (`change.flood_classes`)
* Open water: HH below a threshold chosen by Otsu's method, constrained to −24…−13 dB
  (fallback −18 dB). New water = water now but not in the pre-event baseline.
* Flooded vegetation: HH rises more than 3 dB, HV changes much less (HH−HV gain over 1.5 dB), and the pixel
  is not open water. This is double bounce off the water surface and stems. L-band sees it because
  the 24 cm wave passes through the canopy; C-band mostly does not.
* *Hypothesised drivers (Assam):* extreme monsoon rainfall, braided-channel sedimentation,
  embankment failure, wetland loss. Validate with GPM IMERG and Central Water Commission gauges.

### Fire & forest loss (`change.disturbance_classes`)
* Baseline = median HV of pre-event dates. Loss = HV stays at least 3 dB below baseline for at least 2
  consecutive dates (this filters out rain and wind) and the pixel was vegetated before (HV above −20 dB).
* Grass and shrub fires change L-band HV very little because there is little volume to remove.
  That is an expected *physics result*.

### Agriculture (`change.crop_phenology`)
* The HV time series per pixel gives:
  * **Paddy rice:** a flooding minimum (below −20 dB) followed by a rise of more than 5 dB within 75 days.
  * **Other active crops:** a dynamic range of more than 4 dB.
* We also map the date of peak canopy (HV maximum). This is a radar crop calendar, and it works under monsoon cloud.

### Earthquakes (`insar`, GUNW)
* `d_LOS = −λ/4π · (φ_unw − φ_iono)`, masked where coherence is below 0.3 or the connected component is 0.
  The result is referenced to a far-field ring.
* Rewrapped fringes: one colour cycle = λ/2 = **11.9 cm** of motion along the line of sight (LOS).
* The bar chart compares the pair that spans the event with quiet pairs (signal versus noise floor).
* Strike-slip motion is mostly horizontal. Combining ascending and descending tracks
  (`insar.decompose_asc_desc`) separates east from up.

### Subsidence (GUNW chain)
* Consecutive 12-day pairs are summed and each one is referenced to a stable bedrock box.
  Rates are annualised.
* For publication-grade rates, use SBAS (MintPy) on the full stack and correct the troposphere.

### Glaciers (GOFF)
* Speed = |offset| / Δt. Slant-range offsets are projected to ground range when the incidence angle is known.
* Low-SNR offsets are masked out.
* Phase interferometry decorrelates on fast, melting ice. Offset tracking does not.

## 4. Known limitations (say these out loud: judges reward honesty)

* PROVISIONAL products are calibrated but only partially validated, and processing improvements are ongoing.
* LOS is a 1-D projection of 3-D motion.
* Layover and shadow in steep terrain. Pixels are masked where the product says so, but keep it in mind.
* Water versus smooth surfaces (tarmac, sand) is ambiguous on single dates. Change detection fixes most of it.
* The 12-day revisit misses short floods that drain within days.
* Synthetic demo layers are simulations made with the same code. They are labelled in the UI.

## 5. Future applications of NISAR (for the pitch)

* Near-real-time flood extent under cloud, including flooded-forest alerts, for disaster agencies.
* Paddy area and transplanting dates for food-security and crop-insurance programmes.
* Deforestation alerts that cannot be blocked by cloud or smoke, plus L-band biomass loss estimates.
* InSAR for infrastructure: subsidence under railways, dams and coastal cities; landslide early warning.
* Ice-sheet velocity every 12 days, feeding sea-level projections.
* Dual-frequency (L+S) science: separating canopy (S) from trunk and ground (L) contributions.
