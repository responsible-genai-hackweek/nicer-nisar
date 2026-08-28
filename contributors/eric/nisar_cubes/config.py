"""Regions, storage locations and the variable deny-list."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: ASF's NISAR product bucket and its HTTPS mirror.  A granule's key is the same
#: under both, which is what lets us derive the HTTPS manifest from the S3 one.
NISAR_BUCKET = "sds-n-cumulus-prod-nisar-products"
NISAR_S3_PREFIX = f"s3://{NISAR_BUCKET}/"
NISAR_HTTPS_PREFIX = "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/"
NISAR_REGION = "us-west-2"
S3_CREDS_ENDPOINT = "https://nisar.asf.earthdatacloud.nasa.gov/s3credentials"

#: Groups inside a GCOV file, by band.
HDF_GROUPS = {
    "freqA": "/science/LSAR/GCOV/grids/frequencyA",
    "freqB": "/science/LSAR/GCOV/grids/frequencyB",
}

#: Everything in a grids group that is not a raster or its georeferencing.
#: A fixed deny-list rather than a probe-derived keep-list, because
#: ``inputDataExceptionMask`` and ``listOfPolarizations`` collide on dimensions
#: in frequencyB and quad-pol granules and have to be gone *before* the parser
#: builds the dataset.  Names that are absent from a file are ignored.
DENY_VARIABLES = (
    "inputDataExceptionMask",
    "listOfCovarianceTerms",
    "listOfPolarizations",
    "mask",
    "numberOfLooks",
    "numberOfSubSwaths",
    "rtcGammaToSigmaFactor",
    "xCoordinateSpacing",
    "yCoordinateSpacing",
    # off-diagonal covariance terms, present only if GCOV was run with them
    "HHHV", "HHVH", "HHVV", "HVVH", "HVVV", "VHVV",
)

#: Diagonal covariance terms, i.e. backscatter, in the order we report them.
BACKSCATTER_VARS = ("HHHH", "HVHV", "VVVV", "VHVH")

SCHEMES = ("s3", "https")


@dataclass(frozen=True)
class Region:
    name: str
    bbox: tuple[float, float, float, float]  # west, south, east, north
    description: str = ""
    collections: tuple[str, ...] = ("NISAR_L2_GCOV_PROVISIONAL_V1",)


REGIONS: dict[str, Region] = {
    "wna": Region(
        "wna",
        (-130.0, 30.0, -100.0, 62.0),
        "Western North America: BC, Alberta and southern Yukon to the Mexican "
        "border, Pacific to the Rockies' east flank.",
    ),
    "alaska": Region("alaska", (-170.0, 50.0, -130.0, 72.0), "Alaska and the Yukon."),
    "rainier": Region(
        "rainier", (-121.9, 46.7, -121.6, 46.95), "Mount Rainier — the notebook 1-4 test case."
    ),
}


@dataclass
class Settings:
    """Where the repository, catalog and local working files live.

    Environment overrides: ``NISAR_CUBES_BUCKET``, ``NISAR_CUBES_PREFIX``,
    ``NISAR_CUBES_DATA_DIR``.  ``prefix`` is the *root*; the region name is
    appended, so one bucket holds many regions side by side.
    """

    bucket: str = field(default_factory=lambda: os.environ.get("NISAR_CUBES_BUCKET", "nasa-cryo-persistent"))
    prefix: str = field(default_factory=lambda: os.environ.get("NISAR_CUBES_PREFIX", "egagli/nisar-gcov"))
    region_name: str = "wna"
    aws_region: str = NISAR_REGION
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("NISAR_CUBES_DATA_DIR", Path.home() / "nisar_cubes_data"))
    )
    workers: int = 8
    batch_granules: int = 40  # commit after this many granules have been indexed

    @property
    def region(self) -> Region:
        return REGIONS[self.region_name]

    @property
    def repo_prefix(self) -> str:
        return f"{self.prefix.rstrip('/')}/{self.region_name}"

    @property
    def repo_url(self) -> str:
        return f"s3://{self.bucket}/{self.repo_prefix}"

    @property
    def catalog_url(self) -> str:
        return f"{self.repo_url}/catalog"

    @property
    def local_dir(self) -> Path:
        d = self.data_dir / self.region_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def inventory_path(self) -> Path:
        return self.local_dir / "inventory.parquet"

    @property
    def catalog_path(self) -> Path:
        return self.local_dir / "cubes.parquet"
