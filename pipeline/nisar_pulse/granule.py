"""Parse NISAR granule names.

Example (from the ASF NISAR user guide):
    NISAR_L1_PR_RSLC_004_122_D_067_4005_DHDH_A_20251106T160541_20251106T160622_X05009_N_F_J_001
    S-band (ISRO / Bhoonidhi) follows the same pattern, e.g. NISAR_S2_PR_GCOV_...

Token layout (split on "_"):
    0 NISAR | 1 instrument+level (L1/L2/L3 = L-band, S1/S2 = S-band) | 2 processing type (PR)
    3 product (RSLC, GCOV, GUNW, GOFF, ...) | 4 cycle | 5 relative orbit / track (001-173)
    6 pass direction (A/D) | 7 frame (001-176) | 8 mode | 9 polarisation | 10 accuracy flag
    11 start (YYYYMMDDTHHMMSS) | 12 end | 13 composite release id (CRID) | ... flags/version

Interferometric products (GUNW/GOFF/RIFG...) may carry two start/stop pairs
(reference + secondary). We therefore detect *all* timestamp tokens rather than
trusting fixed positions for dates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

_TS = re.compile(r"^\d{8}T\d{6}$")


@dataclass
class Granule:
    name: str
    band: str  # "L" or "S"
    level: str
    product: str
    cycle: int | None
    track: int | None
    direction: str | None
    frame: int | None
    polarization: str | None
    times: list[datetime] = field(default_factory=list)
    crid: str | None = None

    @property
    def start(self) -> datetime | None:
        return self.times[0] if self.times else None

    @property
    def stack_key(self) -> tuple:
        """Images are only comparable inside the same viewing geometry *and* transmit
        polarisation: a VV-only (DVNA) acquisition in an HH/HV stack would look like change.
        DHDH (HH+HV), QPDH (quad, includes HH+HV) and SH* (HH) share H transmit, so they mix."""
        return (self.band, self.product, self.track, self.direction, self.frame, self.pol_family)

    @property
    def pol_family(self) -> str:
        p = (self.polarization or "").upper()
        return "H" if p[:2] in ("DH", "QP", "SH") else "V" if p[:2] in ("DV", "SV") else p

    @property
    def is_pair(self) -> bool:
        return self.product in {"GUNW", "RUNW", "RIFG", "GOFF", "ROFF"}

    @property
    def reference_secondary(self) -> tuple[datetime | None, datetime | None]:
        """For pair products: (reference start, secondary start).

        Pairs list 4 timestamps (ref start/stop, sec start/stop) in most products.
        """
        if len(self.times) >= 4:
            return self.times[0], self.times[2]
        if len(self.times) >= 2:
            return self.times[0], self.times[1]
        return self.start, None


def _int(tok: str) -> int | None:
    try:
        return int(tok)
    except (TypeError, ValueError):
        return None


def parse(name: str) -> Granule:
    stem = name.rsplit("/", 1)[-1]
    for ext in (".h5", ".zip", ".nc"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
    t = stem.split("_")
    if len(t) < 10 or t[0] != "NISAR":
        raise ValueError(f"Not a NISAR granule name: {name}")
    inst = t[1]
    band = "S" if inst.startswith("S") else "L"
    times = [datetime.strptime(x, "%Y%m%dT%H%M%S") for x in t if _TS.match(x)]
    ts_idx = [i for i, x in enumerate(t) if _TS.match(x)]
    crid = t[ts_idx[-1] + 1] if ts_idx and ts_idx[-1] + 1 < len(t) else None
    return Granule(
        name=stem,
        band=band,
        level=inst[1:],
        product=t[3],
        cycle=_int(t[4]),
        track=_int(t[5]),
        direction=t[6] if t[6] in ("A", "D") else None,
        frame=_int(t[7]),
        polarization=t[9] if len(t) > 9 else None,
        times=times,
        crid=crid,
    )
