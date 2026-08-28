"""NISAR single-acquisition product names.

``NISAR_IL_PT_PROD_CYL_REL_P_FRM_MODE_POLE_S_Start_End_CRID_A_C_LOC_CTR.EXT``
(nisar-docs, *Naming Conventions*).  The fields that matter for stacking are
REL (relative orbit, 001-173), FRM (frame, 001-176) and MODE (bandwidth code of
the primary and secondary bands, two characters each: 40, 20, 77, 05 or 00 =
band absent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

GRANULE_RX = re.compile(
    r"^NISAR_(?P<level>L\d)_(?P<ptype>\w{2})_(?P<product>\w{4})_"
    r"(?P<cycle>\d{3})_(?P<relative_orbit>\d{3})_(?P<direction>[AD])_"
    r"(?P<frame>\d{3})_(?P<mode>\d{4})_(?P<pols>\w{4})_(?P<source>\w)_"
    r"(?P<start>\d{8}T\d{6})_(?P<end>\d{8}T\d{6})_"
    r"(?P<crid>\w{6})_(?P<accuracy>\w)_(?P<coverage>\w)_(?P<location>\w)_(?P<ctr>\d{3})"
    r"(?:\.(?P<ext>\w+))?$"
)

_POL_CHANNELS = {
    "SH": ("HHHH",),
    "SV": ("VVVV",),
    "DH": ("HHHH", "HVHV"),
    "DV": ("VVVV", "VHVH"),
    "QP": ("HHHH", "HVHV", "VVVV", "VHVH"),
    "CL": (), "CR": (), "NA": (),
}


@dataclass(frozen=True)
class GranuleName:
    name: str
    level: str
    ptype: str
    product: str
    cycle: int
    relative_orbit: int
    direction: str
    frame: int
    mode: str
    pols: str
    source: str
    start: datetime
    end: datetime
    crid: str
    accuracy: str
    coverage: str
    location: str
    ctr: int

    # -- identity -----------------------------------------------------------
    @property
    def track_frame(self) -> str:
        """``D172_F065`` — the unit that shares one output grid."""
        return f"{self.direction}{self.relative_orbit:03d}_F{self.frame:03d}"

    @property
    def mode_pols(self) -> str:
        return f"{self.mode}_{self.pols}"

    @property
    def cube_key(self) -> tuple[str, int, int, str, str]:
        """Everything that must match for two granules to share a cube."""
        return (self.direction, self.relative_orbit, self.frame, self.mode, self.pols)

    @property
    def acquisition_key(self) -> tuple:
        """The same take, regardless of product version."""
        return (*self.cube_key, self.start)

    # -- bands ---------------------------------------------------------------
    @property
    def bands(self) -> tuple[str, ...]:
        """Which of freqA / freqB exist, from the mode code (``00`` = absent)."""
        out = []
        if self.mode[:2] != "00":
            out.append("freqA")
        if self.mode[2:] != "00":
            out.append("freqB")
        return tuple(out)

    def channels(self, band: str) -> tuple[str, ...]:
        code = self.pols[:2] if band == "freqA" else self.pols[2:]
        return _POL_CHANNELS.get(code, ())

    @property
    def start_iso(self) -> str:
        return self.start.strftime("%Y-%m-%dT%H:%M:%S")


def parse_granule(name_or_url: str) -> GranuleName:
    name = name_or_url.rsplit("/", 1)[-1]
    m = GRANULE_RX.match(name)
    if not m:
        raise ValueError(f"not a NISAR single-acquisition product name: {name}")
    d = m.groupdict()
    ts = lambda s: datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)  # noqa: E731
    return GranuleName(
        name=name.removesuffix(f".{d['ext']}") if d["ext"] else name,
        level=d["level"], ptype=d["ptype"], product=d["product"],
        cycle=int(d["cycle"]), relative_orbit=int(d["relative_orbit"]),
        direction=d["direction"], frame=int(d["frame"]), mode=d["mode"], pols=d["pols"],
        source=d["source"], start=ts(d["start"]), end=ts(d["end"]),
        crid=d["crid"], accuracy=d["accuracy"], coverage=d["coverage"],
        location=d["location"], ctr=int(d["ctr"]),
    )


def group_path(scheme: str, track_frame: str, mode_pols: str, band: str, grid_id: str | None = None) -> str:
    """``s3/D172_F065/4005_DHDH/freqA`` (``…/freqA_g1a2b3c`` for a second grid)."""
    leaf = band if not grid_id else f"{band}_g{grid_id}"
    return f"{scheme}/{track_frame}/{mode_pols}/{leaf}"
