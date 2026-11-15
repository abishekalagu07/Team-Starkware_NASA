import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nisar_pulse import change, export, geo, granule, insar, sar, workflows  # noqa: E402


def test_granule_parse_rslc_example():
    g = granule.parse("NISAR_L1_PR_RSLC_004_122_D_067_4005_DHDH_A_20251106T160541_20251106T160622_X05009_N_F_J_001")
    assert (g.band, g.product, g.track, g.direction, g.frame, g.polarization) == ("L", "RSLC", 122, "D", 67, "DHDH")
    assert g.start == datetime(2025, 11, 6, 16, 5, 41)
    assert g.crid == "X05009"


def test_granule_parse_sband():
    g = granule.parse("NISAR_S2_PR_GCOV_025_026_D_125_3700_SHNA_A_20260710T004942_20260710T005015_P00500_M_P_I_001")
    assert g.band == "S" and g.product == "GCOV" and g.track == 26 and g.frame == 125


@pytest.mark.parametrize("lon,lat", [(-68.55, 10.37), (94.2, 26.7), (-99.1, 19.4), (30.9, 7.5), (-55.2, -7.2)])
def test_utm_roundtrip(lon, lat):
    epsg = geo.utm_zone_epsg(lon, lat)
    x, y = geo.lonlat_to_xy(lon, lat, epsg)
    lo, la = geo.xy_to_lonlat(x, y, epsg)
    assert abs(lo - lon) < 1e-8 and abs(la - lat) < 1e-8


def test_utm_scale():
    _, y = geo.lonlat_to_xy(-63.0, 1.0, 32620)
    assert abs(float(y) - 110574.4 * 0.9996) < 5  # 1 degree of latitude at the equator


@pytest.mark.parametrize("epsg,lon,lat", [(3413, -49.5, 69.2), (3031, 10.0, -75.0)])
def test_polar_roundtrip(epsg, lon, lat):
    x, y = geo.lonlat_to_xy(lon, lat, epsg)
    lo, la = geo.xy_to_lonlat(x, y, epsg)
    assert abs(lo - lon) < 1e-8 and abs(la - lat) < 1e-8


def test_db_average_in_linear():
    a = np.array([[-10.0]]), np.array([[-20.0]])
    m = sar.nanmean_db(np.stack(a))
    assert abs(m.item() - 10 * np.log10((0.1 + 0.01) / 2)) < 1e-4  # not -15 dB


def test_lee_filter_keeps_mean_and_reduces_variance():
    rng = np.random.default_rng(0)
    img = rng.gamma(4, 0.25, (200, 200)).astype("f4") * 0.05
    f = sar.lee_filter(img, 7, 4)
    assert abs(f.mean() - img.mean()) / img.mean() < 0.02
    assert f.std() < img.std() * 0.6


def test_otsu_bimodal():
    rng = np.random.default_rng(1)
    v = np.concatenate([rng.normal(-24, 1.5, 5000), rng.normal(-8, 1.5, 5000)])
    t = change.otsu_threshold(v)
    assert -20 < t < -12


def test_flood_classes_double_bounce():
    pre = np.full((10, 10), -9.0)
    post = pre.copy()
    post[:5] = -24  # new open water
    post[5:, :3] = -2  # flooded vegetation
    pre_hv = np.full_like(pre, -15.0)
    post_hv = pre_hv.copy()
    cls, _ = change.flood_classes(pre, post, pre_hv, post_hv, water_db=-18)
    assert (cls[:5] == 2).all() and (cls[5:, :3] == 4).all() and (cls[5:, 3:] == 0).all()


def test_disturbance_requires_persistence():
    T = 6
    s = np.full((T, 4, 4), -12.0)
    s[3:, 0, 0] = -18  # persistent loss
    s[4, 1, 1] = -18  # single-date dip (rain/wind) — must NOT be flagged
    cls, _ = change.disturbance_classes(s, n_pre=3, persist=2)
    assert cls[0, 0] == 1 and cls[1, 1] == 0


def test_insar_phase_roundtrip_and_rewrap():
    wl = 0.2384
    d = np.array([0.0, 0.05, -0.1])
    phase = -4 * np.pi / wl * d
    out = insar.los_displacement(phase, wl, sign=-1)
    assert np.allclose(out, d, atol=1e-6)
    assert np.allclose(insar.rewrap(np.array([wl / 2]), wl), 0, atol=1e-6)


def test_decompose_asc_desc_recovers_motion():
    east, up = 0.03, -0.05
    inc_a, head_a, inc_d, head_d = 38, -12, 38, -168
    ea, _, ua = insar.los_unit_vector(inc_a, head_a, "left")
    ed, _, ud = insar.los_unit_vector(inc_d, head_d, "left")
    e2, u2 = insar.decompose_asc_desc(np.array(ea * east + ua * up), np.array(ed * east + ud * up),
                                      inc_a, head_a, inc_d, head_d, "left")
    assert abs(float(e2) - east) < 1e-6 and abs(float(u2) - up) < 1e-6


def test_process_gcov_end_to_end(tmp_path):
    """Full flood workflow on a tiny synthetic stack -> site.json + images + cube."""
    site = {"id": "t", "name": "t", "change_type": "flood", "product": "GCOV", "bbox": [90.0, 25.0, 90.2, 25.2],
            "event_date": "2026-07-10", "story": {"headline": "t"}}
    epsg = geo.utm_zone_epsg(90.1, 25.1)
    xmin, ymin, xmax, ymax = geo.bbox_to_xy_window(site["bbox"], epsg)
    x = np.arange(xmin, xmax, 100.0)
    y = np.arange(ymax, ymin, -100.0)
    rng = np.random.default_rng(3)
    recs = []
    for k in range(5):
        hh = np.full((len(y), len(x)), -9.0)
        if k >= 2:
            hh[: len(y) // 2] = -24
        recs.append({"date": datetime(2026, 7, 1) + timedelta(days=12 * k), "x": x, "y": y, "epsg": epsg, "looks": 6,
                     "data": {"HHHH": sar.from_db(hh) * rng.gamma(6, 1 / 6, hh.shape).astype("f4"),
                              "HVHV": sar.from_db(hh - 7) * rng.gamma(6, 1 / 6, hh.shape).astype("f4")}})
    e = workflows.process_gcov(site, recs, str(tmp_path), max_px=200)
    peak = max(e["charts"][0]["series"][0]["values"])
    area = (0.2 * 111.32 * np.cos(np.radians(25.1))) * (0.2 * 110.54)
    assert 0.35 * area < peak < 0.65 * area  # about half the box flooded
    assert os.path.exists(tmp_path / "sites/t/site.json")
    assert os.path.exists(tmp_path / e["layers"]["frames"]["items"][0]["url"])
    cube = json.load(open(tmp_path / e["layers"]["cube"]))
    assert len(cube["data"]) == 5
    cat = export.build_catalog(str(tmp_path))
    assert json.load(open(cat))["sites"][0]["id"] == "t"


def test_multilook_block_mean_and_coordinates():
    from nisar_pulse import h5io
    a = np.arange(36, dtype="f4").reshape(6, 6)
    a[0, 0] = np.nan                                   # NaNs are ignored inside a block
    rec = {"data": {"HHHH": a}, "x": np.arange(6) * 10.0, "y": 100 - np.arange(6) * 10.0, "looks": 4.0}
    out = h5io.multilook(rec, 3)
    assert out["data"]["HHHH"].shape == (2, 2)
    assert out["data"]["HHHH"][0, 0] == pytest.approx(np.nanmean(a[:3, :3]))
    assert out["data"]["HHHH"][1, 1] == pytest.approx(a[3:, 3:].mean())
    assert list(out["x"]) == [10.0, 40.0] and list(out["y"]) == [90.0, 60.0]   # block centres
    assert out["looks"] == 36.0


def test_http_range_file_reads_across_blocks():
    from nisar_pulse import h5io
    blob = bytes(range(256)) * 40                     # 10240 bytes
    f = h5io.HTTPRangeFile.__new__(h5io.HTTPRangeFile)
    f.url, f.block, f.max, f.retries, f.pos, f.size = "mem", 1000, 3, 1, 0, len(blob)
    f.cache = __import__("collections").OrderedDict()
    f._get = lambda a, b: (blob[a:b + 1], f"bytes {a}-{b}/{len(blob)}")
    f.seek(990)
    assert f.read(25) == blob[990:1015]               # spans two blocks
    f.seek(-10, 2)
    assert f.read() == blob[-10:]
    buf = bytearray(5); f.seek(3); assert f.readinto(buf) == 5 and bytes(buf) == blob[3:8]
    assert len(f.cache) <= 3                          # LRU bound respected


def test_stacks_never_mix_polarisations():
    from nisar_pulse import search
    names = ["NISAR_L2_PR_GCOV_028_077_D_084_4005_DHDH_A_20260818T132026_20260818T132100_P05023_N_F_J_001",
             "NISAR_L2_PR_GCOV_029_077_D_084_2000_DVNA_M_20260830T132026_20260830T132100_P05023_N_F_J_001",
             "NISAR_L2_PR_GCOV_030_077_D_084_4005_DHDH_A_20260911T132026_20260911T132100_P05023_N_F_J_001",
             "NISAR_L2_PR_GCOV_031_077_D_084_2005_QPDH_A_20260923T132026_20260923T132100_P05023_N_F_J_001"]
    res = [{"name": n, "granule": granule.parse(n)} for n in names]
    best = search.best_stack(res)
    # VV-only is excluded; quad-pol (has HH+HV) stays in the HH/HV stack
    assert [r["granule"].polarization for r in best] == ["DHDH", "DHDH", "QPDH"]


def test_lee_filter_survives_nan_looks():
    a = np.full((20, 20), 0.05, "f4"); a[:, :10] = np.nan
    out = sar.lee_filter(a, 5, float("nan"))
    assert np.isfinite(out[:, 12:]).all()            # NaN looks must not blank the image


def test_best_stack_weighs_bbox_coverage():
    from nisar_pulse import search
    def mk(track, day, poly):
        n = f"NISAR_L2_PR_GCOV_028_{track:03d}_D_084_4005_DHDH_A_202608{day:02d}T132026_202608{day:02d}T132100_P05023_N_F_J_001"
        return {"name": n, "granule": granule.parse(n), "geometry": {"type": "Polygon", "coordinates": [poly]}}
    full = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    sliver = [[0.95, 0], [1, 0], [1, 1], [0.95, 1], [0.95, 0]]
    res = [mk(62, d, sliver) for d in range(1, 11)] + [mk(77, d, full) for d in range(1, 7)]
    best = search.best_stack(res, bbox=(0, 0, 1, 1))
    assert best[0]["granule"].track == 77 and search.coverage(best, (0, 0, 1, 1)) == pytest.approx(1.0)


def test_qc_dates_flags_brightened_water_date():
    rng = np.random.default_rng(0)
    T, n = 8, 40
    hh = np.full((T, n, n), -8.0, "f4") + rng.normal(0, 0.5, (T, n, n)).astype("f4")
    hh[:, :, :20] = -20.0                                    # persistent water on the left half
    hh[5, :, :20] = -8.5                                     # one date: water as bright as land
    bad, why = change.qc_dates(hh)
    assert list(np.where(bad)[0]) == [5] and "water" in why[5]
    hh[5, :, :20] = -20.0
    bad, _ = change.qc_dates(hh)
    assert not bad.any()                                     # clean stack: nothing flagged


def test_stacks_keep_one_product_per_acquisition_day():
    from nisar_pulse import search
    names = ["NISAR_L2_PR_GCOV_028_034_D_073_4005_DHDH_A_20260818T013000_20260818T013034_P05023_N_F_J_001",
             "NISAR_L2_PR_GCOV_028_034_D_073_2005_QPDH_A_20260818T013007_20260818T013041_P05023_N_F_J_001",
             "NISAR_L2_PR_GCOV_029_034_D_073_4005_DHDH_A_20260830T013000_20260830T013034_P05023_N_F_J_001"]
    res = [{"name": n, "granule": granule.parse(n)} for n in names]
    (stack,) = search.stacks(res).values()
    assert [r["granule"].start.date().isoformat() for r in stack] == ["2026-08-18", "2026-08-30"]
    assert stack[0]["granule"].polarization == "DHDH"          # dual-pol copy preferred


def test_qc_dates_keeps_landscape_flooding_dates():
    rng = np.random.default_rng(1)
    T, n = 8, 40
    hh = np.full((T, n, n), -8.0, "f4") + rng.normal(0, 0.5, (T, n, n)).astype("f4")
    hh[:3] -= 8.0                       # rice belt flooded for transplanting: whole scene 8 dB darker
    bad, _ = change.qc_dates(hh)
    assert not bad.any()                # darkening is real flooding, never excluded
    hh[6] += 8.0                        # a whole scene 8 dB brighter is not physical
    bad, why = change.qc_dates(hh)
    assert list(np.where(bad)[0]) == [6] and "brighter" in why[6]
