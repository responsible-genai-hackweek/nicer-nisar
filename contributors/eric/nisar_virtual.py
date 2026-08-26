"""Helpers for virtualizing NISAR GCOV granules with VirtualiZarr + Icechunk.

Kept out of the notebook so that ``icechunk.s3_refreshable_credentials`` has a
module-level (picklable) callable to refresh NISAR's hourly S3 tokens with.
"""

from __future__ import annotations

import re

import earthaccess

BUCKET = "sds-n-cumulus-prod-nisar-products"
S3_CREDS_ENDPOINT = "https://nisar.asf.earthdatacloud.nasa.gov/s3credentials"
REGION = "us-west-2"

#: Group holding the frequency-A image grids of a GCOV product.
GCOV_GRIDS = "/science/LSAR/GCOV/grids/frequencyA"

#: NISAR L2 GCOV filename fields we care about, e.g.
#: NISAR_L2_PR_GCOV_004_172_D_065_4005_DHDH_A_20251110T031848_...
GRANULE_RX = re.compile(
    r"NISAR_L2_\w\w_GCOV_(?P<cycle>\d+)_(?P<absorb>\d+)_(?P<direction>[AD])_"
    r"(?P<relorb>\d+)_(?P<frame>\d+)_(?P<pols>\w+)_\w_"
    r"(?P<start>\d{8}T\d{6})_(?P<end>\d{8}T\d{6})_"
)


def nisar_s3_credentials() -> dict:
    """Fetch temporary NISAR S3 credentials (valid ~1 hour) via Earthdata Login."""
    auth = earthaccess.login(strategy="netrc")
    return auth.get_s3_credentials(endpoint=S3_CREDS_ENDPOINT)


def icechunk_credentials():
    """Refresh callback for ``icechunk.s3_refreshable_credentials``.

    Must be importable (not defined in a notebook cell) so icechunk can pickle
    it into the repository config.
    """
    import datetime

    import icechunk

    c = nisar_s3_credentials()
    expires = c["expiration"]
    if isinstance(expires, str):
        # earthaccess hands back an ISO-8601 string; icechunk wants a datetime.
        expires = datetime.datetime.fromisoformat(expires)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    return icechunk.S3StaticCredentials(
        access_key_id=c["accessKeyId"],
        secret_access_key=c["secretAccessKey"],
        session_token=c["sessionToken"],
        expires_after=expires,
    )


def obstore_registry():
    """An ObjectStoreRegistry wired to the NISAR products bucket."""
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import S3Store

    c = nisar_s3_credentials()
    store = S3Store(
        BUCKET,
        region=REGION,
        access_key_id=c["accessKeyId"],
        secret_access_key=c["secretAccessKey"],
        session_token=c["sessionToken"],
    )
    return ObjectStoreRegistry({f"s3://{BUCKET}": store})


def find_track(bbox, short_name="NISAR_L2_GCOV_PROVISIONAL_V1", count=200):
    """Group GCOV granules over ``bbox`` by (direction, relative orbit, frame, pols).

    Returns ``{key: [(start_datetime, s3_url), ...]}`` sorted by acquisition time.
    Grouping matters: only granules that share a track *and* frame are posted to
    the same output grid, which is what VirtualiZarr needs in order to concatenate.
    """
    from collections import defaultdict

    results = earthaccess.search_data(
        short_name=short_name, bounding_box=bbox, count=count
    )
    groups: dict[tuple, list] = defaultdict(list)
    for g in results:
        for url in g.data_links(access="direct"):
            if not url.endswith(".h5"):
                continue
            if m := GRANULE_RX.search(url.rsplit("/", 1)[-1]):
                key = (m["direction"], m["relorb"], m["frame"], m["pols"])
                groups[key].append((m["start"], url))
    return {k: sorted(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
