"""Object storage: interface and adapters."""

from enterprise.storage.base import (
    IntegrityError,
    InvalidKey,
    ObjectNotFound,
    ObjectStore,
    ObjectStoreError,
    StorageUnavailable,
    validate_key,
)
from enterprise.storage.local import LocalObjectStore

__all__ = [
    "IntegrityError",
    "InvalidKey",
    "LocalObjectStore",
    "ObjectNotFound",
    "ObjectStore",
    "ObjectStoreError",
    "StorageUnavailable",
    "validate_key",
]
