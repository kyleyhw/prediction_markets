"""Object storage for the platform's files, and the local cache in front of it.

The engine reads and writes a data root of Parquet files. On the platform
those files live in an object store, shared by every process, and each
process keeps a disk cache it assembles into an engine-shaped data root
when a job or a view needs one. Two backends behind one small interface:

* `LocalStore`, a directory, for development and tests;
* `S3Store`, any S3-compatible service, which is MinIO on the local
  stand-in (flag F16) and the cloud's object storage after the deploy.

Keys are laid out so that almost everything is immutable, which is what
makes a cache that never revalidates correct:

    shared/markets/<domain>/versions/<stamp>.parquet   a dataset version
    shared/markets/<domain>/LATEST                     the current version's stamp
    shared/histories/<domain>/<file>.parquet           a settled market's prices
    shared/snapshots/<domain>/<stamp>.parquet          one capture of open markets
    shared/evidence/<source>/<YYYY-MM-DD>/<stamp>.parquet
    workspaces/<id>/runs/<run>/<file>                  a run's artifacts
    archive/<table>/<YYYYMM>.parquet                   an archived partition

`LATEST` is the one mutable key; it is read through, never cached.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from vp.platform.config import Settings

SHARED = "shared"


class ObjectStore(Protocol):
    """The operations the platform needs, and no others."""

    def put_bytes(self, key: str, data: bytes) -> None:
        """Write an object, replacing any with the same key."""
        ...

    def put_file(self, key: str, path: Path) -> None:
        """Upload a local file."""
        ...

    def get_bytes(self, key: str) -> bytes | None:
        """Read an object, or None when it does not exist."""
        ...

    def download(self, key: str, dest: Path) -> bool:
        """Copy an object to a local path; False when it does not exist."""
        ...

    def keys(self, prefix: str) -> list[str]:
        """Every key under a prefix, sorted."""
        ...

    def delete(self, key: str) -> None:
        """Remove an object if it exists."""
        ...


def _check_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"not a valid object key: {key!r}")
    return key


class LocalStore:
    """An object store in a directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / _check_key(key)

    def put_bytes(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)

    def put_file(self, key: str, path: Path) -> None:
        self.put_bytes(key, path.read_bytes())

    def get_bytes(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def download(self, key: str, dest: Path) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        return True

    def keys(self, prefix: str) -> list[str]:
        base = self.root / prefix
        start = base if base.is_dir() else base.parent
        if not start.exists():
            return []
        found = (
            p.relative_to(self.root).as_posix()
            for p in start.rglob("*")
            if p.is_file() and not p.name.endswith(".part")
        )
        return sorted(k for k in found if k.startswith(prefix))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Store:
    """An object store in an S3-compatible bucket (MinIO locally)."""

    def __init__(self, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self.client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> S3Store:
        import boto3  # imported here: only S3 deployments need it loaded

        bucket = settings.store.removeprefix("s3://").strip("/")
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        return cls(bucket, client)

    def ensure_bucket(self) -> None:
        """Create the bucket if it is missing (development and tests only)."""
        existing = {b["Name"] for b in self.client.list_buckets().get("Buckets", [])}
        if self.bucket not in existing:
            self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=_check_key(key), Body=data)

    def put_file(self, key: str, path: Path) -> None:
        self.client.upload_file(str(path), self.bucket, _check_key(key))

    def get_bytes(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=_check_key(key))
        except self.client.exceptions.NoSuchKey:
            return None
        return response["Body"].read()

    def download(self, key: str, dest: Path) -> bool:
        data = self.get_bytes(key)
        if data is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return True

    def keys(self, prefix: str) -> list[str]:
        found: list[str] = []
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        )
        for page in pages:
            found.extend(obj["Key"] for obj in page.get("Contents", []))
        return sorted(found)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_check_key(key))


def open_store(settings: Settings) -> ObjectStore:
    """The store the settings name."""
    if settings.store.startswith("s3://"):
        return S3Store.from_settings(settings)
    return LocalStore(Path(settings.store.removeprefix("file:")))


# ------------------------------------------------------------ shared files


def publish_dataset(store: ObjectStore, domain: str, path: Path, stamp: str) -> str:
    """Store a resolved dataset as a new version and point LATEST at it."""
    key = f"{SHARED}/markets/{domain}/versions/{stamp}.parquet"
    store.put_file(key, path)
    store.put_bytes(f"{SHARED}/markets/{domain}/LATEST", stamp.encode())
    return key


def publish_tree(
    store: ObjectStore, root: Path, prefix: str, names: Iterable[str]
) -> int:
    """Upload the files under `root/<name>/` to `prefix/<name>/`; returns the count."""
    count = 0
    for name in names:
        base = root / name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.parquet")):
            store.put_file(f"{prefix}/{path.relative_to(root).as_posix()}", path)
            count += 1
    return count


class SharedRoot:
    """The shared files, cached on local disk and laid out as an engine data root.

    `refresh` brings the cache up to date: every immutable key not yet on
    disk is downloaded once, and each domain's `resolved.parquet` is made to
    be the version `LATEST` names. The directory it maintains is a data root
    every engine function reads unchanged.
    """

    def __init__(self, store: ObjectStore, cache: Path) -> None:
        self.store = store
        self.root = cache / "root"

    def refresh(self, domains: Iterable[str], *, snapshots: int | None = 60) -> int:
        """Sync the cache; returns how many files were downloaded.

        Args:
            domains: the domains to bring up to date.
            snapshots: keep only this many newest snapshots per domain in the
                cache (None keeps every one), since views and cycles read the
                recent ones.
        """
        fetched = 0
        for domain in domains:
            fetched += self._dataset(domain)
            fetched += self._mirror(f"{SHARED}/histories/{domain}/", None)
            fetched += self._mirror(f"{SHARED}/snapshots/{domain}/", snapshots)
        return fetched

    def _dataset(self, domain: str) -> int:
        stamp = self.store.get_bytes(f"{SHARED}/markets/{domain}/LATEST")
        if stamp is None:
            return 0
        version = stamp.decode().strip()
        target = self.root / "markets" / domain / "resolved.parquet"
        marker = target.with_suffix(".version")
        if target.exists() and marker.exists() and marker.read_text() == version:
            return 0
        key = f"{SHARED}/markets/{domain}/versions/{version}.parquet"
        if not self.store.download(key, target):
            return 0
        marker.write_text(version)
        return 1

    def _mirror(self, prefix: str, newest: int | None) -> int:
        keys = self.store.keys(prefix)
        if newest is not None:
            keys = keys[-newest:]
        fetched = 0
        for key in keys:
            dest = self.root / key.removeprefix(SHARED + "/")
            if not dest.exists() and self.store.download(key, dest):
                fetched += 1
        return fetched

    def workroot(self, directory: Path) -> Path:
        """A fresh data root for one job: the shared files linked in, the
        rest of the directory the job's own to write."""
        directory.mkdir(parents=True, exist_ok=True)
        for name in ("markets", "histories", "snapshots"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
            link = directory / name
            if not link.exists():
                link.symlink_to((self.root / name).resolve(), target_is_directory=True)
        return directory
