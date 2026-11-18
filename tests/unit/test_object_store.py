"""The encrypted, content-addressed object store."""

from __future__ import annotations

import hashlib
import multiprocessing
from pathlib import Path

import pytest

from omniosint.core.crypto import generate_key
from omniosint.core.paths import AppPaths
from omniosint.core.secrets import OBJECT_STORE_KEY, SecretStore
from omniosint.evidence.objectstore import ObjectCorrupted, ObjectMissing, ObjectStore, object_key

CONTENT = b'{"records": [1, 2, 3]}' * 50


def test_round_trip_and_deduplication(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path, generate_key())
    first = store.put(CONTENT)
    second = store.put(CONTENT)
    assert first.sha256 == hashlib.sha256(CONTENT).hexdigest() and first.created
    assert not second.created
    assert store.get(first.sha256) == CONTENT
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 1


def test_files_are_encrypted_and_named_without_the_hash(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path, generate_key())
    stored = store.put(CONTENT)
    (path,) = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert stored.sha256 not in str(path)
    data = path.read_bytes()
    assert b"records" not in data


def test_tampering_and_a_wrong_key_are_detected(tmp_path: Path) -> None:
    key = generate_key()
    store = ObjectStore(tmp_path, key)
    stored = store.put(CONTENT)
    (path,) = [path for path in tmp_path.rglob("*") if path.is_file()]
    # Another key derives other file names, so the object is simply not found...
    other = ObjectStore(tmp_path / "other", generate_key())
    with pytest.raises(ObjectMissing):
        other.get(stored.sha256)
    # ...and a file moved to where that key would look cannot be decrypted.
    moved = other._path(stored.sha256)
    moved.parent.mkdir(parents=True)
    moved.write_bytes(path.read_bytes())
    with pytest.raises(ObjectCorrupted):
        other.get(stored.sha256)
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(ObjectCorrupted):
        store.get(stored.sha256)


def test_missing_and_deleted_objects(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path, generate_key())
    with pytest.raises(ObjectMissing):
        store.get("0" * 64)
    stored = store.put(CONTENT)
    assert store.delete(stored.sha256) and not store.exists(stored.sha256)
    assert not store.delete(stored.sha256)
    with pytest.raises(ValueError, match="SHA-256"):
        store.get("../../etc/passwd")


def _read_key(home: str, queue: multiprocessing.Queue[bytes]) -> None:
    queue.put(object_key(SecretStore(AppPaths.resolve(Path(home)))))


def test_the_object_key_is_created_once_across_processes(tmp_path: Path) -> None:
    paths = AppPaths.resolve(tmp_path)
    paths.ensure()
    context = multiprocessing.get_context("spawn")
    results: multiprocessing.Queue[bytes] = context.Queue()
    workers = [context.Process(target=_read_key, args=(str(tmp_path), results)) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=60)
    keys = {results.get(timeout=5) for _ in workers}
    assert len(keys) == 1
    assert SecretStore(paths).names() == [OBJECT_STORE_KEY]
