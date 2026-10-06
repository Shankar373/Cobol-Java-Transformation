"""Typed control-plane errors with an explicit HTTP status mapping.

Every service/store failure is raised as an :class:`ApiError` subtype so the
HTTP layer can map it deterministically instead of guessing:

    not found ................. 404  NotFoundError
    invalid request ........... 400  ServiceError / InvalidRequestError
    conflict ................. 409  ConflictError
    payload too large ......... 413  PayloadTooLargeError
    no free execution slot .... 429  BusyError
    persistence corruption ..... 500  PersistenceCorruptionError

``public_detail`` is the only text that may reach an HTTP client.  It is
truncated and never carries tracebacks, SQL, filesystem paths or raw payload
bytes; internal detail stays available on the exception object for logging.
"""

from __future__ import annotations

_MAX_DETAIL_CHARS = 500


def _truncate(text: str) -> str:
    flat = " ".join(str(text).split())
    if len(flat) <= _MAX_DETAIL_CHARS:
        return flat
    return flat[: _MAX_DETAIL_CHARS - 1] + "\u2026"


class ApiError(Exception):
    """Base class for every raised control-plane error."""

    status_code: int = 500
    default_detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = _truncate(detail) if detail else self.default_detail
        super().__init__(self.detail)

    @property
    def public_detail(self) -> str:
        """Client-safe message (already truncated, never a traceback)."""
        return self.detail


class ServiceError(ApiError):
    """Service-level operation failure (default: invalid request, 400)."""

    status_code = 400
    default_detail = "Invalid request"


class NotFoundError(ServiceError):
    """Referenced application/run/resource does not exist."""

    status_code = 404
    default_detail = "Resource not found"


class ConflictError(ServiceError):
    """Operation conflicts with the current lifecycle state of a run."""

    status_code = 409
    default_detail = "Operation conflicts with the current run state"


class PayloadTooLargeError(ApiError):
    """Upload exceeds a configured request/file/file-count limit."""

    status_code = 413
    default_detail = "Upload exceeds the configured size limit"


class BusyError(ApiError):
    """No execution slot available for new expensive background work."""

    status_code = 429
    default_detail = "Too many concurrent jobs; retry later"


class PersistenceCorruptionError(ApiError):
    """Persisted state is malformed, unsupported or fails integrity checks.

    Raised instead of fabricating a default (``CREATED``, ``None``, ``()``)
    so corruption is always visible as a controlled server error.
    """

    status_code = 500
    default_detail = "Persisted state failed integrity validation"


class InvalidStateTransitionError(PersistenceCorruptionError):
    """A run stage transition violates the declared lifecycle state machine."""

    default_detail = "Invalid run state transition"


class UnsupportedSchemaError(PersistenceCorruptionError):
    """Persisted payload uses an unknown/unsupported schema version."""

    default_detail = "Unsupported persisted schema version"
