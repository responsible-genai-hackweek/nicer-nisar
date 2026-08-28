"""Earthdata Login, object stores for the NISAR bucket, and the Icechunk repository.

Three credential lifetimes are in play and each is handled separately:

* **Repository storage** (our bucket) — the hub's IAM role via the environment;
  never expires.
* **Reading NISAR pixels over S3** — hourly EDL tokens; Icechunk refreshes them
  through :func:`icechunk_s3_credentials`, which must be a module-level callable.
* **Reading NISAR pixels over HTTPS** — an EDL bearer token, good for weeks,
  passed as a header on the ``http_store`` container at open time.  Never
  persisted in the repository config.
"""

from __future__ import annotations

import datetime as dt
import functools

from . import config as C


@functools.cache
def earthdata_login():
    import earthaccess

    return earthaccess.login(strategy="netrc")


def nisar_s3_credentials() -> dict:
    """Temporary S3 credentials for the NISAR bucket (valid ~1 h)."""
    return earthdata_login().get_s3_credentials(endpoint=C.S3_CREDS_ENDPOINT)


def icechunk_s3_credentials():
    """Refresh callback for ``icechunk.s3_refreshable_credentials`` (picklable)."""
    import icechunk

    c = nisar_s3_credentials()
    exp = c["expiration"]
    if isinstance(exp, str):
        exp = dt.datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=dt.timezone.utc)
    return icechunk.S3StaticCredentials(
        access_key_id=c["accessKeyId"],
        secret_access_key=c["secretAccessKey"],
        session_token=c["sessionToken"],
        expires_after=exp,
    )


def edl_bearer_token() -> str:
    tok = earthdata_login().token
    return tok["access_token"]


def nisar_s3_store():
    """An obstore ``S3Store`` on the NISAR bucket that refreshes its own credentials."""
    import earthaccess
    from obstore.auth.earthdata import NasaEarthdataCredentialProvider
    from obstore.store import S3Store

    earthdata_login()
    provider = NasaEarthdataCredentialProvider(
        C.S3_CREDS_ENDPOINT, session=earthaccess.get_requests_https_session()
    )
    return S3Store(C.NISAR_BUCKET, region=C.NISAR_REGION, credential_provider=provider)


def nisar_registry():
    """VirtualiZarr ``ObjectStoreRegistry`` resolving ``s3://<nisar bucket>/...``."""
    from obspec_utils.registry import ObjectStoreRegistry

    return ObjectStoreRegistry({C.NISAR_S3_PREFIX.rstrip("/"): nisar_s3_store()})


# ---------------------------------------------------------------------------
# Icechunk repository
# ---------------------------------------------------------------------------


def repo_config(https_token: str | None = None):
    """Repository config with both virtual chunk containers.

    The ``https`` container's headers are supplied by the opener; the persisted
    config carries none.
    """
    import icechunk

    cfg = icechunk.RepositoryConfig.default()
    cfg.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(C.NISAR_S3_PREFIX, icechunk.s3_store(region=C.NISAR_REGION))
    )
    headers = {"Authorization": f"Bearer {https_token}"} if https_token else None
    cfg.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(C.NISAR_HTTPS_PREFIX, icechunk.http_store(headers=headers))
    )
    return cfg


def virtual_chunk_auth(schemes=C.SCHEMES):
    import icechunk

    auth = {}
    if "s3" in schemes:
        auth[C.NISAR_S3_PREFIX] = icechunk.Credentials.S3(
            icechunk.s3_refreshable_credentials(icechunk_s3_credentials)
        )
    if "https" in schemes:
        auth[C.NISAR_HTTPS_PREFIX] = icechunk.Credentials.HttpAccess()
    return auth


def repo_storage(settings: C.Settings):
    import icechunk

    return icechunk.s3_storage(
        bucket=settings.bucket, prefix=settings.repo_prefix, region=settings.aws_region, from_env=True
    )


def open_repo(settings: C.Settings | None = None, *, create: bool = False, schemes=C.SCHEMES):
    """Open (or create) the region's repository, authorised to read NISAR chunks.

    ``schemes`` controls which credentials are fetched: the S3 refresh callback
    only works in ``us-west-2``; the HTTPS token works anywhere.
    """
    import icechunk

    settings = settings or C.Settings()
    token = edl_bearer_token() if "https" in schemes else None
    storage = repo_storage(settings)
    kwargs = dict(
        storage=storage, config=repo_config(token), authorize_virtual_chunk_access=virtual_chunk_auth(schemes)
    )
    if create:
        return icechunk.Repository.open_or_create(**kwargs)
    return icechunk.Repository.open(**kwargs)
