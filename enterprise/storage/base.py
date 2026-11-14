"""Provider-neutral object storage interface.

Objects are immutable once written. ``put`` and multipart completion verify the
SHA-256 (and size limit) while streaming, so an object that fails verification
is never visible. ``ObjectRef.version`` is the content SHA-256: the same bytes
always have the same version, which is what resume and publication compare.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import BinaryIO, Protocol

from enterprise.contracts import ObjectRef

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_KEY_LENGTH = 512
MAX_PART_NUMBER = 10_000
CHUNK = 1 << 20


class ObjectStoreError(Exception):
    """Base class for storage failures."""


class InvalidKey(ObjectStoreError):
    pass


class ObjectNotFound(ObjectStoreError):
    pass


class IntegrityError(ObjectStoreError):
    """The bytes do not match the expected checksum or size."""


class StorageUnavailable(ObjectStoreError):
    """The backend could not be reached; the caller may retry."""


def validate_key(key: str) -> str:
    """Accept ``a/b/c.dat`` style keys only: no traversal, no absolute paths."""
    if not key or len(key) > MAX_KEY_LENGTH or key.startswith("/") or key.endswith("/"):
        raise InvalidKey(f"invalid object key {key[:80]!r}")
    for segment in key.split("/"):
        if segment in (".", "..") or not _SEGMENT.match(segment):
            raise InvalidKey(f"invalid object key segment {segment[:40]!r}")
    return key


class ObjectStore(Protocol):
    def put(
        self,
        key: str,
        stream: BinaryIO,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> ObjectRef: ...

    def open(self, key: str) -> BinaryIO: ...

    def stat(self, key: str) -> ObjectRef: ...

    def verify(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str = "") -> Iterator[str]: ...

    def create_multipart(self, key: str) -> str: ...

    def upload_part(self, key: str, upload_id: str, part_number: int, data: bytes) -> str: ...

    def complete_multipart(
        self,
        key: str,
        upload_id: str,
        parts: list[tuple[int, str]],
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> ObjectRef: ...

    def abort_multipart(self, key: str, upload_id: str) -> None: ...
