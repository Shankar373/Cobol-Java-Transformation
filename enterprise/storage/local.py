"""Local filesystem object store (development and single-node deployments).

Layout under ``root``: ``objects/<key>`` plus ``objects/<key>.meta.json``,
``.tmp/`` for in-flight writes, ``.multipart/<upload_id>/`` for open uploads.
Every write goes to a temporary file and is renamed into place only after the
checksum has been verified.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from enterprise.contracts import ObjectRef
from enterprise.quotas import IngestionQuotas, QuotaExceeded
from enterprise.storage.base import (
    CHUNK,
    MAX_PART_NUMBER,
    IntegrityError,
    InvalidKey,
    ObjectNotFound,
    validate_key,
)

_META = ".meta.json"


class LocalObjectStore:
    def __init__(self, root: Path, quotas: IngestionQuotas | None = None) -> None:
        self._root = Path(root)
        self._objects = self._root / "objects"
        self._tmp = self._root / ".tmp"
        self._multipart = self._root / ".multipart"
        self._quotas = quotas or IngestionQuotas()
        for folder in (self._objects, self._tmp, self._multipart):
            folder.mkdir(parents=True, exist_ok=True)

    # -- helpers ---------------------------------------------------------
    def _path(self, key: str) -> Path:
        validate_key(key)
        if key.endswith(_META):
            raise InvalidKey("keys may not end with the metadata suffix")
        path = (self._objects / key).resolve()
        if self._objects.resolve() not in path.parents:
            raise InvalidKey("key escapes the store")
        return path

    @staticmethod
    def _meta_path(path: Path) -> Path:
        return path.with_name(path.name + _META)

    def _publish(self, tmp: Path, key: str, sha256: str, size: int) -> ObjectRef:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = path.parent / f".{uuid.uuid4().hex}.meta.tmp"
        meta.write_text(json.dumps({"size": size, "sha256": sha256}), encoding="utf-8")
        os.replace(meta, self._meta_path(path))
        os.replace(tmp, path)
        return ObjectRef(key=key, size=size, sha256=sha256, version=sha256)

    # -- single-shot objects ----------------------------------------------
    def put(self, key: str, stream: BinaryIO, *, expected_sha256: str | None = None,
            max_bytes: int | None = None) -> ObjectRef:
        self._path(key)
        tmp = self._tmp / uuid.uuid4().hex
        digest, size = hashlib.sha256(), 0
        try:
            with tmp.open("wb") as sink:
                for block in iter(lambda: stream.read(CHUNK), b""):
                    size += len(block)
                    if max_bytes is not None and size > max_bytes:
                        raise QuotaExceeded("object_bytes", size, max_bytes)
                    digest.update(block)
                    sink.write(block)
                sink.flush()
                os.fsync(sink.fileno())
            if expected_sha256 and digest.hexdigest() != expected_sha256:
                raise IntegrityError("checksum does not match the expected SHA-256")
            return self._publish(tmp, key, digest.hexdigest(), size)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.open("rb")

    def stat(self, key: str) -> ObjectRef:
        path = self._path(key)
        meta = self._meta_path(path)
        if not path.is_file() or not meta.is_file():
            raise ObjectNotFound(key)
        info = json.loads(meta.read_text(encoding="utf-8"))
        return ObjectRef(key=key, size=info["size"], sha256=info["sha256"], version=info["sha256"])

    def verify(self, key: str) -> bool:
        ref = self.stat(key)
        digest, size = hashlib.sha256(), 0
        with self.open(key) as handle:
            for block in iter(lambda: handle.read(CHUNK), b""):
                digest.update(block)
                size += len(block)
        return size == ref.size and digest.hexdigest() == ref.sha256

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        self._meta_path(path).unlink(missing_ok=True)

    def list(self, prefix: str = "") -> Iterator[str]:
        for path in sorted(self._objects.rglob("*")):
            if path.is_file() and not path.name.endswith(_META) and not path.name.startswith("."):
                key = path.relative_to(self._objects).as_posix()
                if key.startswith(prefix):
                    yield key

    # -- multipart --------------------------------------------------------
    def _upload_dir(self, upload_id: str) -> Path:
        if not upload_id.isalnum():
            raise InvalidKey("invalid upload id")
        return self._multipart / upload_id

    def create_multipart(self, key: str) -> str:
        self._path(key)
        upload_id = uuid.uuid4().hex
        folder = self._upload_dir(upload_id)
        folder.mkdir()
        (folder / "key").write_text(key, encoding="utf-8")
        return upload_id

    def _checked_upload(self, key: str, upload_id: str) -> Path:
        folder = self._upload_dir(upload_id)
        if not folder.is_dir() or (folder / "key").read_text(encoding="utf-8") != key:
            raise ObjectNotFound(f"upload {upload_id}")
        return folder

    def upload_part(self, key: str, upload_id: str, part_number: int, data: bytes) -> str:
        folder = self._checked_upload(key, upload_id)
        if not 1 <= part_number <= min(MAX_PART_NUMBER, self._quotas.multipart_max_parts):
            raise InvalidKey(f"part number {part_number} out of range")
        if len(data) > self._quotas.multipart_part_max_bytes:
            raise QuotaExceeded("multipart_part_max_bytes", len(data), self._quotas.multipart_part_max_bytes)
        etag = hashlib.sha256(data).hexdigest()
        tmp = folder / f".{part_number}.{uuid.uuid4().hex}"
        tmp.write_bytes(data)
        os.replace(tmp, folder / f"{part_number:05d}.part")  # re-upload replaces the part
        return etag

    def complete_multipart(self, key: str, upload_id: str, parts: list[tuple[int, str]], *,
                           expected_sha256: str, expected_size: int) -> ObjectRef:
        folder = self._checked_upload(key, upload_id)
        numbers = [n for n, _ in parts]
        if not parts or numbers != sorted(set(numbers)):
            raise IntegrityError("parts must be listed once each in ascending order")
        tmp = self._tmp / uuid.uuid4().hex
        digest, size = hashlib.sha256(), 0
        try:
            with tmp.open("wb") as sink:
                for index, (number, etag) in enumerate(parts):
                    part = folder / f"{number:05d}.part"
                    if not part.is_file():
                        raise IntegrityError(f"part {number} was never uploaded")
                    data = part.read_bytes()
                    if hashlib.sha256(data).hexdigest() != etag:
                        raise IntegrityError(f"part {number} does not match its checksum")
                    if index < len(parts) - 1 and len(data) < self._quotas.multipart_part_min_bytes:
                        raise IntegrityError(f"part {number} is smaller than the minimum part size")
                    size += len(data)
                    digest.update(data)
                    sink.write(data)
            if size != expected_size or digest.hexdigest() != expected_sha256:
                raise IntegrityError("assembled object does not match the declared size and SHA-256")
            ref = self._publish(tmp, key, digest.hexdigest(), size)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        shutil.rmtree(folder, ignore_errors=True)
        return ref

    def abort_multipart(self, key: str, upload_id: str) -> None:
        shutil.rmtree(self._upload_dir(upload_id), ignore_errors=True)
