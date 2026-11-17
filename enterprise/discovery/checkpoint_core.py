"""Shared types and pure helpers of the checkpoint modules.

Split out of ``checkpoint`` to keep each module cohesive: this module holds the
schema constants, the metadata/report value types, the identity functions and
two filesystem-free or read-only predicates.  Import the public API from
``enterprise.discovery.checkpoint``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Union

from .errors import IngestionError
from .model import IngestedFile

SCHEMA_VERSION = "systemaops.checkpoint/1.0"
KINDS = ("git", "zip", "directory")

CHECKPOINT_FILE = "checkpoint.json"
SOURCE_DIR = "source"
ORIGINAL_DIR = "original"
ORIGINAL_ARCHIVE = "input.zip"

_ID_RE = re.compile(r"CP-[0-9a-f]{32}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})?")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_TIMESTAMP_RE = re.compile(
    r"(?:\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|[+-]\d\d:\d\d)?)?"
)
MAX_TEXT = 2048

#: Seal strengths recorded in ``checkpoint.json`` (``seal_kind``).
SEAL_SHA256 = "sha256"
SEAL_HMAC = "hmac-sha256"
SEAL_KINDS = (SEAL_SHA256, SEAL_HMAC)
#: Environment variable holding the operator's store key (never stored).
KEY_ENV = "SYSTEMAOPS_STORE_KEY"

_RESERVED_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_IS_WINDOWS = os.name == "nt"

FileLike = Union[IngestedFile, "tuple[str, str, int]"]

@dataclass(frozen=True)
class VerificationReport:
    """Outcome of :func:`verify_checkpoint`.

    Directories are reported with a trailing ``/`` so they cannot be confused
    with files.  ``ok`` is true only when nothing at all deviates.
    """

    ok: bool
    digest_ok: bool
    modified: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class _MetadataError(Exception):
    """``checkpoint.json`` is absent, unparseable or violates the schema."""


@dataclass(frozen=True)
class _Meta:
    checkpoint_id: str
    kind: str
    origin: str
    ref: str
    commit: str
    tree_id: str
    commit_timestamp: str
    archive_sha256: str
    source_digest: str
    file_count: int
    directory_count: int
    total_bytes: int
    files: tuple[tuple[str, str, int], ...]
    directories: tuple[str, ...]
    #: ``seal_kind``/``seal`` as recorded, and the canonical bytes the seal
    #: covers (the whole document minus ``seal``); empty while creating.
    seal_kind: str = ""
    seal: str = ""
    canonical: bytes = b""


def _err(code: str, message: str, path: str | None = None) -> IngestionError:
    return IngestionError(message, code=code, path=path)


def _as_triple(item: FileLike) -> tuple[str, str, int]:
    if isinstance(item, IngestedFile):
        return (item.path, item.sha256, item.size)
    path, sha, size = item
    return (str(path), str(sha), int(size))


def compute_source_digest(files: Iterable[FileLike]) -> str:
    """sha256 over ``"<path>\\0<sha256>\\0<size>\\n"`` sorted by path."""

    digest = hashlib.sha256()
    for path, sha, size in sorted(_as_triple(f) for f in files):
        record = f"{path}\0{sha}\0{size}\n"
        digest.update(record.encode("utf-8", "surrogatepass"))
    return digest.hexdigest()


def make_checkpoint_id(kind: str, commit: str | None, source_digest: str) -> str:
    """``CP-`` plus the first 32 hex of ``sha256(kind NUL commit NUL digest)``."""

    raw = f"{kind}\0{commit or ''}\0{source_digest}".encode("utf-8")
    return "CP-" + hashlib.sha256(raw).hexdigest()[:32]



def _is_safe_relative(path: str) -> bool:
    """Structural check for a recorded relative POSIX path (no filesystem)."""

    if not isinstance(path, str) or not path or len(path) > 4096:
        return False
    if "\\" in path or ":" in path or _CONTROL_RE.search(path):
        return False
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if any(_is_windows_unsafe(part) for part in parts):
        return False
    return PurePosixPath(path).as_posix() == path


def _is_windows_unsafe(component: str) -> bool:
    """Reserved device names (with or without extension) and trailing dot/space."""

    if component != component.rstrip(" ."):
        return True
    return component.split(".", 1)[0].upper() in _RESERVED_DEVICES


def valid_text(value: object, pattern: "re.Pattern[str] | None" = None) -> bool:
    """A short printable string, optionally matching *pattern* completely."""

    if not isinstance(value, str) or len(value) > MAX_TEXT or _CONTROL_RE.search(value):
        return False
    return pattern is None or pattern.fullmatch(value) is not None


def _nfc(path: str) -> str:
    return unicodedata.normalize("NFC", path)


def _fold(path: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", path).casefold())


def find_collision(paths: Iterable[str]) -> str | None:
    """A path that collides with another under casefold or NFC, else ``None``.

    Also reports a file whose folded name equals a folded parent directory of
    another path.  Such pairs overwrite each other on case-insensitive or
    normalising filesystems.
    """

    seen: set[str] = set()
    dir_keys: set[str] = set()
    spellings: dict[str, str] = {}
    ordered = sorted(paths)
    for path in ordered:
        key = _fold(path)
        if key in seen:
            return path
        seen.add(key)
        parts = key.split("/")
        raw_parts = _nfc(path).split("/")
        for i in range(1, len(parts)):
            folded, spelled = "/".join(parts[:i]), "/".join(raw_parts[:i])
            if spellings.setdefault(folded, spelled) != spelled:
                return path
            dir_keys.add(folded)
    return next((p for p in ordered if _fold(p) in dir_keys), None)


def store_key() -> bytes | None:
    """The operator's store key from ``SYSTEMAOPS_STORE_KEY``, or ``None`` when unset."""

    value = os.environ.get(KEY_ENV, "")
    return value.encode("utf-8") if value else None


def canonical_bytes(document: dict) -> bytes:
    """Serialise *document* minus ``seal`` exactly as ``checkpoint.json`` is."""

    body = {k: v for k, v in document.items() if k != "seal"}
    return json.dumps(body, sort_keys=True, indent=2, ensure_ascii=True).encode("ascii")


def seal_digest(data: bytes, key: bytes | None) -> str:
    """HMAC-SHA256 under *key*, or plain SHA-256 when there is no key."""

    if key:
        return hmac.new(key, data, hashlib.sha256).hexdigest()
    return hashlib.sha256(data).hexdigest()


def compute_seal(document: dict, key: bytes | None) -> str:
    """Seal over the whole *document* minus its ``seal`` entry."""

    return seal_digest(canonical_bytes(document), key)



def _is_plain(real_root: str, path: Path, rel: str) -> bool:
    """True when *path* is neither a symlink nor a junction/redirect."""

    if path.is_symlink():
        return False
    expected = os.path.join(real_root, *rel.split("/"))
    return os.path.normcase(os.path.realpath(path)) == os.path.normcase(expected)

