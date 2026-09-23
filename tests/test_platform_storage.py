"""Object storage and the shared cache, against a directory and an
in-process S3 (moto), so both backends run offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from vp.platform.config import load_settings
from vp.platform.storage import (
    LocalStore,
    S3Store,
    SharedRoot,
    open_store,
    publish_dataset,
)


@pytest.fixture(params=["local", "s3"])
def store(request, tmp_path: Path):
    if request.param == "local":
        yield LocalStore(tmp_path / "store")
        return
    import boto3
    from moto import mock_aws

    with mock_aws():
        s3 = S3Store("vp-test", boto3.client("s3", region_name="us-east-1"))
        s3.ensure_bucket()
        yield s3


def test_objects_round_trip_and_list_by_prefix(store, tmp_path: Path) -> None:
    store.put_bytes("shared/snapshots/cs2/b.parquet", b"two")
    store.put_bytes("shared/snapshots/cs2/a.parquet", b"one")
    store.put_bytes("shared/snapshots/epl/a.parquet", b"x")
    assert store.keys("shared/snapshots/cs2/") == [
        "shared/snapshots/cs2/a.parquet",
        "shared/snapshots/cs2/b.parquet",
    ]
    assert store.get_bytes("shared/snapshots/cs2/a.parquet") == b"one"
    assert store.get_bytes("shared/missing") is None
    assert store.download("shared/snapshots/cs2/b.parquet", tmp_path / "out" / "b")
    assert (tmp_path / "out" / "b").read_bytes() == b"two"
    store.delete("shared/snapshots/cs2/b.parquet")
    assert store.get_bytes("shared/snapshots/cs2/b.parquet") is None


def test_keys_that_could_escape_are_refused(store) -> None:
    for key in ("../etc/passwd", "/abs", "shared//x", "shared/./x", ""):
        with pytest.raises(ValueError):
            store.put_bytes(key, b"")


def test_the_cache_is_an_engine_data_root(store, tmp_path: Path) -> None:
    dataset = tmp_path / "resolved.parquet"
    dataset.write_bytes(b"v1")
    publish_dataset(store, "epl", dataset, "20260901T000000Z")
    for stamp in ("20260923T100000Z", "20260923T110000Z", "20260923T120000Z"):
        store.put_bytes(f"shared/snapshots/epl/{stamp}.parquet", stamp.encode())
    shared = SharedRoot(store, tmp_path / "cache")
    assert shared.refresh(["epl"], snapshots=2) == 3  # the dataset and two snapshots
    assert shared.refresh(["epl"], snapshots=2) == 0  # immutable keys fetched once
    root = shared.root
    assert (root / "markets/epl/resolved.parquet").read_bytes() == b"v1"
    assert sorted(p.name for p in (root / "snapshots/epl").iterdir()) == [
        "20260923T110000Z.parquet",
        "20260923T120000Z.parquet",
    ]
    # A new dataset version replaces the cached one.
    dataset.write_bytes(b"v2")
    publish_dataset(store, "epl", dataset, "20260923T130000Z")
    assert shared.refresh(["epl"]) >= 1
    assert (root / "markets/epl/resolved.parquet").read_bytes() == b"v2"
    # A job's root sees the shared files and writes only its own.
    work = shared.workroot(tmp_path / "job")
    assert (work / "markets/epl/resolved.parquet").read_bytes() == b"v2"
    (work / "paper").mkdir()
    assert not (root / "paper").exists()


def test_the_settings_choose_the_backend(tmp_path: Path) -> None:
    local = open_store(
        load_settings({"VP_DATABASE_URL": "x", "VP_DATA_ROOT": str(tmp_path)})
    )
    assert isinstance(local, LocalStore) and local.root == tmp_path / "store"
    s3 = open_store(
        load_settings(
            {
                "VP_DATABASE_URL": "x",
                "VP_STORE": "s3://vp-data",
                "VP_S3_ENDPOINT": "http://127.0.0.1:9000",
                "VP_S3_ACCESS_KEY": "minio",
                "VP_S3_SECRET_KEY": "minio-secret",  # pragma: allowlist secret
            }
        )
    )
    assert isinstance(s3, S3Store) and s3.bucket == "vp-data"
